// @vitest-environment node
import { readFileSync } from 'node:fs';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { operationalBinding as binding } from './operational-fixture';

const state = vi.hoisted(() => ({
  handlers: new Map<string, (...args: unknown[]) => Promise<unknown>>(),
  connections: new Map<string, unknown[]>(),
  orders: vi.fn(), lease: vi.fn(), dedicated: vi.fn(), atomic: vi.fn(), close: vi.fn(),
}));
vi.mock('../../apps/cockpit/rayfin/functions/node_modules/@microsoft/fabric-user-data-functions', () => ({
  AudienceType: { Sql: 'Sql', Fabric: 'Fabric' },
  UserDataFunctions: class {
    func(name: string, handler: (...args: unknown[]) => Promise<unknown>, connections: unknown[]) {
      state.handlers.set(name, handler); state.connections.set(name, connections);
    }
  },
}));
vi.mock('../../apps/cockpit/rayfin/functions/src/operational-connection', () => ({ withOperationalPool: state.lease }));
vi.mock('../../apps/cockpit/rayfin/functions/src/operational-orders', async importOriginal => ({
  ...await importOriginal<object>(), readOperationalOrders: state.orders,
}));
vi.mock('../../apps/cockpit/rayfin/functions/src/storage', () => ({ poolFor: state.dedicated, atomic: state.atomic }));

const page = { rentals: [], playback: [], orders: { page: 1, pageSize: 50, total: 0 },
  sessions: { page: 1, pageSize: 50, total: 0 } };
const command = { entity_key: 'order', status: 'booked', event_ids: ['event'] };
let lookup: ReturnType<typeof vi.fn>;
let grants: ReturnType<typeof vi.fn>;
let ctx: { getDataClient: ReturnType<typeof vi.fn>; Tokens: { Sql: string } };
beforeEach(async () => {
  vi.resetModules(); vi.clearAllMocks(); state.handlers.clear(); state.connections.clear();
  state.orders.mockResolvedValue(page);
  state.lease.mockImplementation(async (_binding: unknown, _token: unknown, read: (pool: unknown) => Promise<unknown>) =>
    read({ request: () => ({ query: async () => ({ recordset: [{ pending: 7 }] }) }) }));
  state.dedicated.mockResolvedValue({ close: state.close });
  state.atomic.mockResolvedValue(command);
  lookup = vi.fn().mockResolvedValue([binding]);
  grants = vi.fn().mockResolvedValue([]);
  ctx = { Tokens: { Sql: 'invocation-sql-token' }, getDataClient: vi.fn(() => ({
    RuntimeBinding: { select: () => ({ where: () => ({ execute: lookup }) }) },
    OperatorGrant: { select: () => ({ execute: grants }) },
  })) };
  // Cold UDF dependency compilation can exceed the default hook budget in combined runs.
  await import('../../apps/cockpit/rayfin/functions/src/function_app');
}, 30_000);
const invoke = (name: string, ...args: unknown[]) => state.handlers.get(name)!(...args);

describe('operational UDF registration and authorization boundary', () => {
  it('registers primitive paging parameters with a SQL context and the exported result type', async () => {
    const source = readFileSync(new URL('../../apps/cockpit/rayfin/functions/src/function_app.ts', import.meta.url), 'utf8');
    expect(source).toMatch(/udf\.func\('operationalOrders', async \(ordersPage: number, playbackPage: number,\s*ctx: RayfinContext<AppSchema, AudienceType\.Sql>\): Promise<OperationalOrdersPage>/);
    expect(state.connections.get('operationalOrders')).toEqual([]);
    expect(await invoke('operationalOrders', 2, 3, ctx)).toEqual(page);
    expect(state.orders).toHaveBeenCalledExactlyOnceWith(binding, ctx.Tokens.Sql, 2, 3);
  });

  it('allows the existing authenticated viewer without requesting an operator grant', async () => {
    expect(await invoke('operationalOrders', 1, 1, ctx)).toEqual(page);
    expect(grants).not.toHaveBeenCalled(); expect(lookup).toHaveBeenCalledOnce();
    expect(state.dedicated).not.toHaveBeenCalled(); expect(state.atomic).not.toHaveBeenCalled();
  });

  it('rejects invalid paging before binding lookups or SQL', async () => {
    await expect(invoke('operationalOrders', 0, 1, ctx)).rejects.toThrow('ordersPage');
    await expect(invoke('operationalOrders', 1, 0, ctx)).rejects.toThrow('playbackPage');
    expect(ctx.getDataClient).not.toHaveBeenCalled(); expect(state.orders).not.toHaveBeenCalled();
  });

  it('does not bypass caller-scoped binding authorization for paging or health', async () => {
    lookup.mockRejectedValue(new Error('Caller is not authenticated'));
    await expect(invoke('operationalOrders', 1, 1, ctx)).rejects.toThrow('not authenticated');
    await expect(invoke('health', ctx)).rejects.toThrow('not authenticated');
    expect(state.orders).not.toHaveBeenCalled(); expect(state.lease).not.toHaveBeenCalled();
  });

  it.each([
    { name: 'missing', rows: [] },
    { name: 'duplicate', rows: [binding, binding] },
    { name: 'unverified', rows: [{ ...binding, verified: false }] },
  ])('fails closed for $name binding rows', async ({ rows }) => {
    lookup.mockResolvedValue(rows);
    await expect(invoke('operationalOrders', 1, 1, ctx)).rejects.toThrow('not bound');
    expect(state.orders).not.toHaveBeenCalled();
  });

  it('uses the read lease for health without changing its response or viewer semantics', async () => {
    expect(await invoke('health', ctx)).toEqual({ database: 'App-linked SQL and expected tables verified',
      functions: 'Native UDF invocation verified', outbox_pending: 7,
      broker: 'Delivery is acknowledged by the external producer, not by this app.' });
    expect(state.lease).toHaveBeenCalledExactlyOnceWith(binding, ctx.Tokens.Sql, expect.any(Function));
    expect(grants).not.toHaveBeenCalled(); expect(state.dedicated).not.toHaveBeenCalled();
    await invoke('health', ctx); expect(lookup).toHaveBeenCalledTimes(2);
  });

  it('retains command grant checks and the dedicated transaction/close lifecycle', async () => {
    const grant = { id: 'grant', user_id: 'operator', enabled: true, expires_at: new Date('2099-01-01') };
    grants.mockResolvedValue([grant]);
    const input = { idempotency_key: 'key', customer_key: 'customer', offer_key: 'offer' };
    expect(await invoke('placeOrder', input, ctx)).toEqual(command);
    expect(grants).toHaveBeenCalledOnce(); expect(state.dedicated).toHaveBeenCalledExactlyOnceWith(binding, ctx.Tokens.Sql);
    expect(state.atomic).toHaveBeenCalledExactlyOnceWith({ close: state.close }, grant, 'key', 'placeOrder', input, expect.any(Function));
    expect(state.close).toHaveBeenCalledOnce(); expect(state.lease).not.toHaveBeenCalled();
  });

  it('closes a failed command once without replay or a read lease', async () => {
    grants.mockResolvedValue([{ id: 'grant', user_id: 'operator', enabled: true, expires_at: new Date('2099-01-01') }]);
    state.atomic.mockRejectedValue(new Error('command failed'));
    await expect(invoke('placeOrder', { idempotency_key: 'key' }, ctx)).rejects.toThrow('command failed');
    expect(state.atomic).toHaveBeenCalledOnce(); expect(state.close).toHaveBeenCalledOnce(); expect(state.lease).not.toHaveBeenCalled();
  });

  it('still rejects commands without an operator grant before opening SQL', async () => {
    await expect(invoke('placeOrder', { idempotency_key: 'key' }, ctx)).rejects.toThrow();
    expect(state.dedicated).not.toHaveBeenCalled(); expect(state.atomic).not.toHaveBeenCalled(); expect(state.lease).not.toHaveBeenCalled();
  });
});
