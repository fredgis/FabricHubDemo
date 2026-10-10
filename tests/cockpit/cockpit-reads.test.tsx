import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { GoldPages } from '../../apps/cockpit/rayfin/functions/src/gold-pages';
import type { Snapshot } from '../../apps/cockpit/src/services/business';

const readers = vi.hoisted(() => ({ gold: vi.fn(), operational: vi.fn() }));
vi.mock('../../apps/cockpit/src/services/goldViews', () => ({ loadGoldViews: readers.gold }));
vi.mock('../../apps/cockpit/src/services/business', () => ({
  loadSnapshot: readers.operational,
  safeError: (error: Error) => error.message,
}));
import { useCockpitReads } from '../../apps/cockpit/src/hooks/useCockpitReads';

const snapshot: Snapshot = {
  content: [], customers: [], offers: [], rentals: [], playback: [], outbox: [],
  commands: [], campaigns: [], members: [], links: [],
};
const pages: GoldPages = {
  dashboard: {
    source: { name: 'MSFlixGold', workspace_id: 'workspace', item_id: 'gold', views: [] },
    state: 'empty', freshness: { queried_at: '2026-10-08T19:00:00Z', published_at: '2026-10-08T18:00:00Z',
      publication_run_id: 'fixture', order_lines: '0' },
    commercial: [], playback: [], campaigns: [], dimensions: { customers: '0', content: '0' },
  },
  catalog: [], customers: [], offers: [], orders: [], sessions: [], campaigns: [],
  window: { orders: 6, sessions: 6, references: 10000 },
};
const gold = { pages, snapshot };
beforeEach(() => {
  vi.clearAllMocks();
  readers.gold.mockResolvedValue(gold);
  readers.operational.mockResolvedValue(snapshot);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it('loads only the selected Gold page and delays operational collections until they are needed', async () => {
  const { result, rerender } = renderHook(({ section }) => useCockpitReads(section),
    { initialProps: { section: 'overview' } });
  await waitFor(() => expect(result.current.gold).toBe(gold));
  expect(readers.gold).toHaveBeenCalledWith('overview');
  expect(readers.operational).not.toHaveBeenCalled();
  rerender({ section: 'catalog' });
  await waitFor(() => expect(readers.gold).toHaveBeenCalledWith('catalog'));
  rerender({ section: 'graph' });
  expect(readers.operational).not.toHaveBeenCalled();
  expect(readers.gold).toHaveBeenCalledTimes(2);
  rerender({ section: 'insights' });
  expect(readers.operational).not.toHaveBeenCalled();
  expect(readers.gold).toHaveBeenCalledTimes(2);
  rerender({ section: 'orders' });
  await waitFor(() => expect(result.current.snapshot).toBe(snapshot));
  expect(readers.operational).toHaveBeenCalledOnce();
  rerender({ section: 'overview' });
  expect(result.current.gold).toBe(gold);
  expect(readers.gold).toHaveBeenCalledTimes(2);
});

it('keeps the last Gold content visible during refresh and a failed refresh', async () => {
  const { result } = renderHook(() => useCockpitReads('overview'));
  await waitFor(() => expect(result.current.gold).toBe(gold));
  let reject!: (error: Error) => void;
  readers.gold.mockImplementationOnce(() => new Promise((_, fail) => { reject = fail; }));
  let refreshed!: Promise<void>;
  act(() => { refreshed = result.current.refresh(); });
  expect(result.current.goldLoading).toBe(true);
  expect(result.current.gold).toBe(gold);
  await act(async () => { reject(new Error('Gold unavailable')); await refreshed; });
  expect(result.current.gold).toBe(gold);
  expect(result.current.goldError).toBe('Gold unavailable');
  expect(result.current.goldLoading).toBe(false);
});

it('coalesces duplicate explicit refresh requests rather than querying twice', async () => {
  const { result } = renderHook(() => useCockpitReads('overview'));
  await waitFor(() => expect(result.current.gold).toBe(gold));
  let finish!: (value: typeof gold) => void;
  readers.gold.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  let first!: Promise<void>;
  let second!: Promise<void>;
  act(() => { first = result.current.refresh(); second = result.current.refresh(); });
  expect(readers.gold).toHaveBeenCalledTimes(2);
  await act(async () => { finish(gold); await Promise.all([first, second]); });
});

it('caches each operational screen separately and revalidates only after stale reactivation', async () => {
  let now = Date.parse('2026-10-10T12:00:00Z');
  vi.spyOn(Date, 'now').mockImplementation(() => now);
  const snapshots = { orders: { ...snapshot }, demo: { ...snapshot }, operations: { ...snapshot } };
  readers.operational.mockImplementation(async (scope: keyof typeof snapshots) => snapshots[scope]);
  const { result, rerender } = renderHook(({ section }) => useCockpitReads(section),
    { initialProps: { section: 'orders' } });
  await waitFor(() => expect(result.current.snapshot).toBe(snapshots.orders));
  for (const scope of ['demo', 'operations'] as const) {
    rerender({ section: scope });
    expect(result.current.snapshot).toBeNull();
    await waitFor(() => expect(result.current.snapshot).toBe(snapshots[scope]));
  }
  expect(readers.operational.mock.calls).toEqual([['orders'], ['demo'], ['operations']]);
  rerender({ section: 'orders' });
  expect(result.current.snapshot).toBe(snapshots.orders);
  const updated = result.current.updated;
  now += 30_001;
  rerender({ section: 'orders' });
  await act(async () => {});
  expect(readers.operational).toHaveBeenCalledTimes(3);
  rerender({ section: 'graph' });
  rerender({ section: 'orders' });
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(readers.operational).toHaveBeenCalledTimes(4);
  expect(readers.operational).toHaveBeenLastCalledWith('orders');
  expect(result.current.updated).not.toEqual(updated);
});

it('keeps last-good scoped data on refresh failure without leaking errors or providing a Gold fallback', async () => {
  const { result, rerender } = renderHook(({ section }) => useCockpitReads(section),
    { initialProps: { section: 'orders' } });
  await waitFor(() => expect(result.current.snapshot).toBe(snapshot));
  const updated = result.current.updated;
  readers.operational.mockRejectedValueOnce(new Error('Orders unavailable'));
  await act(async () => { await result.current.refresh(); });
  expect(result.current.snapshot).toBe(snapshot);
  expect(result.current.updated).toBe(updated);
  expect(result.current.error).toBe('Orders unavailable');
  expect(result.current.loading).toBe(false);
  rerender({ section: 'operations' });
  expect(result.current.snapshot).toBeNull();
  expect(result.current.error).toBe('');
  await waitFor(() => expect(result.current.loading).toBe(false));
  readers.gold.mockRejectedValueOnce(new Error('Gold unavailable'));
  rerender({ section: 'overview' });
  await waitFor(() => expect(result.current.goldError).toBe('Gold unavailable'));
  expect(result.current.snapshot).toBeNull();
  expect(result.current.gold).toBeUndefined();
  expect(result.current.error).toBe('');
  expect(readers.operational).toHaveBeenCalledTimes(3);
});

it('reloads the currently selected scope after a command and invalidates other fresh caches', async () => {
  const { result, rerender } = renderHook(({ section }) => useCockpitReads(section),
    { initialProps: { section: 'orders' } });
  await waitFor(() => expect(result.current.snapshot).toBe(snapshot));
  const afterCommand = result.current.refresh;
  rerender({ section: 'operations' });
  await waitFor(() => expect(result.current.loading).toBe(false));
  const authoritative = { ...snapshot };
  readers.operational.mockResolvedValueOnce(authoritative);
  await act(async () => { await afterCommand(); });
  expect(readers.operational).toHaveBeenLastCalledWith('operations');
  expect(result.current.snapshot).toBe(authoritative);
  rerender({ section: 'orders' });
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(readers.operational.mock.calls).toEqual([['orders'], ['operations'], ['operations'], ['orders']]);
});

it.each(['demo', 'operations'])('coalesces scope reads on return and keeps a late Orders response out of %s', async scope => {
  let finishOrders!: (value: Snapshot) => void;
  let finishSelected!: (value: Snapshot) => void;
  readers.operational.mockImplementationOnce(() => new Promise(resolve => { finishOrders = resolve; }))
    .mockImplementationOnce(() => new Promise(resolve => { finishSelected = resolve; }));
  const { result, rerender } = renderHook(({ section }) => useCockpitReads(section),
    { initialProps: { section: 'orders' } });
  rerender({ section: scope });
  rerender({ section: 'orders' });
  expect(readers.operational.mock.calls).toEqual([['orders'], [scope]]);
  rerender({ section: scope });
  const selectedSnapshot = { ...snapshot };
  await act(async () => { finishSelected(selectedSnapshot); });
  const updated = result.current.updated;
  await act(async () => { finishOrders(snapshot); });
  expect(result.current.snapshot).toBe(selectedSnapshot);
  expect(result.current.updated).toBe(updated);
  expect(result.current.loading).toBe(false);
  expect(result.current.error).toBe('');
  rerender({ section: 'orders' });
  expect(result.current.snapshot).toBe(snapshot);
  expect(readers.operational).toHaveBeenCalledTimes(2);
});

it.each([
  ['success', 'before'], ['failure', 'before'], ['success', 'after'], ['failure', 'after'],
] as const)('ignores a pre-refresh request’s %s %s the authoritative response', async (outcome, timing) => {
  let finish!: (value: Snapshot) => void;
  let fail!: (error: Error) => void;
  let finishRefresh!: (value: Snapshot) => void;
  readers.operational.mockImplementationOnce(() => new Promise((resolve, reject) => { finish = resolve; fail = reject; }))
    .mockImplementationOnce(() => new Promise(resolve => { finishRefresh = resolve; }));
  const { result, rerender } = renderHook(({ section }) => useCockpitReads(section),
    { initialProps: { section: 'orders' } });
  let refreshed!: Promise<void>;
  act(() => { refreshed = result.current.refresh(); });
  if (timing === 'after') await act(async () => { finishRefresh(snapshot); await refreshed; });
  const updated = result.current.updated;
  await act(async () => {
    if (outcome === 'success') finish({ ...snapshot });
    else fail(new Error('Obsolete read failed'));
  });
  expect(result.current.snapshot).toBe(timing === 'before' ? null : snapshot);
  expect(result.current.updated).toBe(updated);
  expect(result.current.loading).toBe(timing === 'before');
  expect(result.current.error).toBe('');
  if (timing === 'before') await act(async () => { finishRefresh(snapshot); await refreshed; });
  expect(result.current.snapshot).toBe(snapshot);
  expect(result.current.updated).toBeInstanceOf(Date);
  expect(result.current.loading).toBe(false);
  rerender({ section: 'graph' });
  rerender({ section: 'orders' });
  expect(result.current.snapshot).toBe(snapshot);
  expect(readers.operational).toHaveBeenCalledTimes(2);
});
