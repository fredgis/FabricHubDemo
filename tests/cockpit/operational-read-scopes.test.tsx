import { cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const client = vi.hoisted(() => ({
  read: vi.fn(), ledger: vi.fn(),
  entities: ['Content', 'Customer', 'Offer', 'Rental', 'Playback', 'Outbox',
    'ControlCommand', 'Campaign', 'CampaignMember', 'IntegrationLink'],
}));
vi.mock('../../apps/cockpit/src/services/rayfinClient', () => ({
  getRayfinClient: () => ({ data: Object.fromEntries(client.entities.map(entity => [entity, {
    select: (fields: string[]) => {
      let order: unknown;
      let limit: number;
      let cursor: string | undefined;
      const query = {
        orderBy: (value: unknown) => { order = value; return query; },
        first: (value: number) => { limit = value; return query; },
        after: (value: string) => { cursor = value; return query; },
        executePaginated: async () => client.read(entity, { fields, order, limit, cursor }),
        execute: async () => (await client.read(entity, { fields, order, limit, cursor })).items,
      };
      return query;
    },
  }])), functions: { operationalOrders: { invoke: client.ledger } } }),
}));
vi.mock('../../apps/cockpit/src/services/goldViews', () => ({ loadGoldViews: vi.fn(async () => ({})) }));
import { useCockpitReads } from '../../apps/cockpit/src/hooks/useCockpitReads';
import { loadSnapshot, revenueByCurrency } from '../../apps/cockpit/src/services/business';

beforeEach(() => {
  client.read.mockReset();
  client.read.mockResolvedValue({ items: [], hasNextPage: false });
  client.ledger.mockReset();
  client.ledger.mockResolvedValue({ rentals: [], playback: [],
    orders: { page: 1, pageSize: 50, total: 0 }, sessions: { page: 1, pageSize: 50, total: 0 } });
});
afterEach(cleanup);

const scopes = [
  ['orders', ['Content', 'Customer', 'Offer']],
  ['demo', ['Content', 'Customer', 'Offer', 'Outbox', 'ControlCommand']],
  ['operations', ['ControlCommand', 'IntegrationLink']],
] as const;
it.each(scopes)('reads only the operational collections consumed by %s', async (section, entities) => {
  const { result } = renderHook(() => useCockpitReads(section));
  await waitFor(() => expect(result.current.snapshot).not.toBeNull());
  expect(client.read).toHaveBeenCalledTimes(entities.length);
  expect(client.read.mock.calls.map(([entity]) => entity)).toEqual(entities);
  if (section === 'orders') expect(client.ledger).toHaveBeenCalledExactlyOnceWith({ ordersPage: 1, playbackPage: 1 });
  else expect(client.ledger).not.toHaveBeenCalled();
});

it('preserves full default reads and all selected pages, fields, ordering and the bounded outbox window', async () => {
  client.read.mockImplementation(async (entity, { cursor }) => ({
    items: [{ id: `${entity}:${cursor ?? 'first'}` }], hasNextPage: !cursor, endCursor: 'next',
  }));
  const full = await loadSnapshot();
  const fullRequests = [...client.read.mock.calls];
  const collections = {
    content: 'Content', customers: 'Customer', offers: 'Offer', rentals: 'Rental', playback: 'Playback',
    outbox: 'Outbox', commands: 'ControlCommand', campaigns: 'Campaign', members: 'CampaignMember', links: 'IntegrationLink',
  } as const;
  expect(fullRequests).toHaveLength(19);
  expect(Object.keys(full)).toEqual(Object.keys(collections));
  for (const [key, entity] of Object.entries(collections)) {
    expect(full[key as keyof typeof collections].map(row => row.id)).toEqual(entity === 'Outbox'
      ? ['Outbox:first'] : [`${entity}:first`, `${entity}:next`]);
  }
  expect(fullRequests.find(([entity]) => entity === 'Outbox')?.[1])
    .toMatchObject({ order: { occurred_at: 'desc' }, limit: 1000, cursor: undefined });

  for (const [scope, entities] of scopes) {
    client.read.mockClear();
    client.ledger.mockClear();
    const result = await loadSnapshot(scope);
    const included = new Set<string>(entities);
    expect(client.read.mock.calls).toEqual(fullRequests.filter(([entity]) => included.has(entity)));
    expect(client.ledger).toHaveBeenCalledTimes(scope === 'orders' ? 1 : 0);
    for (const [key, entity] of Object.entries(collections)) {
      expect(result[key as keyof typeof result], `${scope}:${key}`)
        .toEqual(included.has(entity) ? full[key as keyof typeof full] : []);
    }
  }
});

it.each([
  ['service failure', 'Operational source unavailable'],
  ['stuck cursor', 'Data pagination did not advance.'],
  ['page limit', 'safe read limit'],
])('rejects the scoped snapshot on %s rather than exposing partial records', async (failure, message) => {
  let page = 0;
  client.read.mockImplementation(async entity => {
    if (entity !== 'ControlCommand') return { items: [], hasNextPage: false };
    if (failure === 'service failure') throw new Error(message);
    return { items: [{ id: `command:${++page}` }], hasNextPage: true,
      endCursor: failure === 'stuck cursor' ? 'same' : String(page) };
  });
  await expect(loadSnapshot('operations')).rejects.toThrow(message);
  expect(page).toBe(failure === 'service failure' ? 0 : failure === 'stuck cursor' ? 2 : 200);
});

it('uses the typed ledger page and preserves server totals instead of downloading both collections', async () => {
  const ledger = { rentals: [{ id: 'fixture-order-page-3' }], playback: [{ id: 'fixture-session-page-2' }],
    orders: { page: 3, pageSize: 50, total: 107 }, sessions: { page: 2, pageSize: 50, total: 58 } };
  client.ledger.mockResolvedValueOnce(ledger);
  const result = await loadSnapshot('orders', { ordersPage: 3, playbackPage: 2 });
  expect(client.ledger).toHaveBeenCalledExactlyOnceWith({ ordersPage: 3, playbackPage: 2 });
  expect(result.rentals).toBe(ledger.rentals);
  expect(result.playback).toBe(ledger.playback);
  expect(result.pagination).toEqual({ orders: ledger.orders, sessions: ledger.sessions });
  expect(client.read.mock.calls.map(([entity]) => entity)).toEqual(['Content', 'Customer', 'Offer']);
  expect(() => revenueByCurrency(result)).toThrow('Global sales totals require a complete snapshot.');
});

it('reuses caller-scoped references for page changes without re-reading or sending them to the UDF', async () => {
  const references = { content: [], customers: [], offers: [] };
  const result = await loadSnapshot('orders', { ordersPage: 2, playbackPage: 4, references });
  expect(client.read).not.toHaveBeenCalled();
  expect(client.ledger).toHaveBeenCalledExactlyOnceWith({ ordersPage: 2, playbackPage: 4 });
  for (const key of ['content', 'customers', 'offers'] as const) expect(result[key]).toBe(references[key]);
});

it('rejects a failed ledger read rather than returning references as an empty ledger', async () => {
  client.ledger.mockRejectedValueOnce(new Error('Fixture ledger unavailable'));
  await expect(loadSnapshot('orders')).rejects.toThrow('Fixture ledger unavailable');
});
