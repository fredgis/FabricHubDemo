// @vitest-environment node
import { EventEmitter } from 'node:events';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { AnalyticsBinding } from '../../apps/cockpit/rayfin/data/schema';

const calls = vi.hoisted(() => ({
  connections: 0, closes: 0, publication: 'first',
  queryError: null as Error | null, connectError: null as Error | null,
  requests: [] as Record<string, unknown>[], instances: [] as EventEmitter[], configs: [] as unknown[],
}));
vi.mock('../../apps/cockpit/rayfin/functions/node_modules/mssql', () => ({
  default: {
    Int: 'Int', VarChar: () => 'VarChar',
    ConnectionPool: class extends EventEmitter {
      constructor(config: unknown) { super(); calls.instances.push(this); calls.configs.push(config); }
      async connect() { calls.connections++; if (calls.connectError) throw calls.connectError; return this; }
      async close() { calls.closes++; }
      request() {
        const inputs: Record<string, unknown> = {};
        const request = {
          input: (name: string, _type: unknown, value: unknown) => { inputs[name] = value; return request; },
          query: async () => {
            calls.requests.push(inputs);
            if (calls.queryError) throw calls.queryError;
            return { recordsets: [[], [], [], [{ customers: '0', content: '0' }],
              [{ run_id: calls.publication, completed_at: '2026-10-10T10:00:00Z', order_lines: '0' }], [], [], [], [], [], []] };
          },
        };
        return request;
      }
    },
  },
}));
const binding: AnalyticsBinding = {
  id: 'binding', binding_key: 'business-gold', name: 'MSFlixGold', verified: true,
  sql_server: 'fixture.datawarehouse.fabric.microsoft.com',
  item_id: '55555555-5555-4555-8555-555555555555', sql_database: '55555555-5555-4555-8555-555555555555',
  workspace_id: 'workspace', capacity_id: 'capacity',
};
const token = (identity = 'a', ttl = 3600) => `header.${Buffer.from(JSON.stringify({
  sub: identity, exp: Math.floor(Date.now() / 1000) + ttl,
})).toString('base64url')}.signature`;
let readPages: typeof import('../../apps/cockpit/rayfin/functions/src/gold-pages').readGoldPages;
let readDashboard: typeof import('../../apps/cockpit/rayfin/functions/src/gold-dashboard').readGoldDashboard;
let withPool: typeof import('../../apps/cockpit/rayfin/functions/src/gold-connection').withGoldPool;
beforeEach(async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-10T10:00:00Z'));
  vi.resetModules();
  Object.assign(calls, { connections: 0, closes: 0, publication: 'first', queryError: null, connectError: null, requests: [], instances: [], configs: [] });
  ({ readGoldPages: readPages } = await import('../../apps/cockpit/rayfin/functions/src/gold-pages'));
  ({ readGoldDashboard: readDashboard } = await import('../../apps/cockpit/rayfin/functions/src/gold-dashboard'));
  ({ withGoldPool: withPool } = await import('../../apps/cockpit/rayfin/functions/src/gold-connection'));
});
afterEach(async () => { await vi.runOnlyPendingTimersAsync(); vi.useRealTimers(); });

it('shares only the connection, returning a new publication on every explicit read', async () => {
  const credential = token();
  expect((await readDashboard(binding, credential)).freshness.publication_run_id).toBe('first');
  calls.publication = 'second';
  expect((await readPages(binding, credential, 'overview')).dashboard.freshness.publication_run_id).toBe('second');
  expect(calls.connections).toBe(1);
  expect(calls.requests).toHaveLength(2);
  expect(calls.closes).toBe(0);
});
it('coalesces concurrent connection setup without sharing request parameters', async () => {
  const credential = token();
  await Promise.all([readPages(binding, credential, 'overview'), readPages(binding, credential, 'catalog')]);
  expect(calls.connections).toBe(1);
  expect(calls.requests.map(request => request.view)).toEqual(['overview', 'catalog']);
});
it('isolates credentials, targets and verified workspace/capacity bindings', async () => {
  const credential = token();
  await readPages(binding, credential);
  await readPages(binding, token('b'));
  await readPages({ ...binding, sql_server: 'other.datawarehouse.fabric.microsoft.com' }, credential);
  await readPages({ ...binding, workspace_id: 'other-workspace' }, credential);
  await readPages({ ...binding, capacity_id: 'other-capacity' }, credential);
  expect(calls.connections).toBe(5);
  expect(calls.closes).toBe(1);
});
it('uses a transient connection when all four cached pools are busy', async () => {
  const credentials = ['a', 'b', 'c', 'd'].map(identity => token(identity));
  const releases: (() => void)[] = [];
  const pending = credentials.map(credential => withPool(binding, credential,
    () => new Promise<void>(resolve => { releases.push(resolve); })));
  await vi.waitFor(() => expect(releases).toHaveLength(4));
  await readPages(binding, token('overflow'));
  expect(calls.connections).toBe(5);
  expect(calls.closes).toBe(1);
  releases.forEach(release => release());
  await Promise.all(pending);
  await readPages(binding, credentials[0]);
  expect(calls.connections).toBe(5);
});
it('drains an active expired pool without sharing it with a new read', async () => {
  const credential = token('short', 80);
  let finish!: () => void;
  const pending = withPool(binding, credential, () => new Promise<void>(resolve => { finish = resolve; }));
  await vi.waitFor(() => expect(finish).toBeTypeOf('function'));
  await vi.advanceTimersByTimeAsync(21_000);
  expect(calls.closes).toBe(0);
  await readPages(binding, credential);
  expect(calls.connections).toBe(2);
  expect(calls.closes).toBe(1);
  finish();
  await pending;
  expect(calls.closes).toBe(2);
});
it('revalidates the binding before using a warm connection', async () => {
  const credential = token();
  await readPages(binding, credential);
  await expect(readPages({ ...binding, verified: false }, credential)).rejects.toThrow('not verified');
  expect(calls.requests).toHaveLength(1);
});
it('reuses both the cached pool and physical connections after a two-minute pause without keepalive', async () => {
  const credential = token();
  await readPages(binding, credential);
  await vi.advanceTimersByTimeAsync(120_000);
  expect(calls.closes).toBe(0);
  expect(calls.requests).toHaveLength(1);
  await readPages(binding, credential);
  expect(calls.connections).toBe(1);
  expect(calls.requests).toHaveLength(2);
  expect(calls.configs[0]).toMatchObject({ pool: { min: 0, max: 2, idleTimeoutMillis: 300_000 } });
});
it('closes a pool after five minutes idle, measured from its last completed read', async () => {
  const credential = token();
  await readPages(binding, credential);
  await vi.advanceTimersByTimeAsync(120_000);
  await readPages(binding, credential);
  await vi.advanceTimersByTimeAsync(299_999);
  expect(calls.closes).toBe(0);
  expect(calls.connections).toBe(1);
  await vi.advanceTimersByTimeAsync(1);
  expect(calls.closes).toBe(1);
  await readPages(binding, credential);
  expect(calls.connections).toBe(2);
});
it('retires before token expiry and does not cache opaque or nearly expired credentials', async () => {
  await readPages(binding, token('short', 80));
  await vi.advanceTimersByTimeAsync(20_000);
  expect(calls.closes).toBe(1);
  for (const credential of ['opaque', token('near', 30)]) {
    await readPages(binding, credential);
    await readPages(binding, credential);
  }
  expect(calls.connections).toBe(5);
  expect(calls.closes).toBe(5);
});
it('bounds connection lifetime to fifteen minutes even under repeated consultation', async () => {
  const credential = token();
  for (let i = 0; i < 5; i++) {
    await readPages(binding, credential);
    expect(calls.connections).toBe(1);
    await vi.advanceTimersByTimeAsync(180_000);
  }
  expect(calls.closes).toBe(1);
  await readPages(binding, credential);
  expect(calls.connections).toBe(2);
});
it('discards failed SQL sessions rather than returning a possibly open transaction to the cache', async () => {
  const credential = token();
  calls.queryError = new Error('SQL batch failed');
  await expect(readPages(binding, credential)).rejects.toThrow();
  expect(calls.closes).toBe(1);
  calls.queryError = null;
  await readPages(binding, credential);
  expect(calls.connections).toBe(2);
});
it('removes a failed login and allows the next read to establish a clean connection', async () => {
  const credential = token();
  calls.connectError = Object.assign(new Error('login failed'), { code: 'ELOGIN' });
  await expect(readPages(binding, credential)).rejects.toThrow();
  calls.connectError = null;
  await readPages(binding, credential);
  expect(calls.connections).toBe(2);
  expect(calls.closes).toBe(1);
});
it('handles background driver errors by retiring the idle pool', async () => {
  const credential = token();
  await readPages(binding, credential);
  calls.instances[0].emit('error', new Error('disconnected'));
  expect(calls.closes).toBe(1);
  await readPages(binding, credential);
  expect(calls.connections).toBe(2);
});
it('does not close an in-use connection when a concurrent reader fails', async () => {
  const credential = token();
  let finish!: () => void;
  const pending = withPool(binding, credential, () => new Promise<void>(resolve => { finish = resolve; }));
  await vi.waitFor(() => expect(finish).toBeTypeOf('function'));
  await expect(withPool(binding, credential, async () => { throw new Error('failed'); })).rejects.toThrow('failed');
  expect(calls.closes).toBe(0);
  finish();
  await pending;
  expect(calls.closes).toBe(1);
});
