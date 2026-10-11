import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { GoldPages } from '../../apps/cockpit/rayfin/functions/src/gold-pages';
import type { Snapshot } from '../../apps/cockpit/src/services/business';

const readers = vi.hoisted(() => ({ gold: vi.fn(), operational: vi.fn() }));
vi.mock('../../apps/cockpit/src/services/goldViews', () => ({ loadGoldViews: readers.gold }));
vi.mock('../../apps/cockpit/src/services/business', () => ({
  loadSnapshot: readers.operational, safeError: (error: Error) => error.message,
}));
import { useCockpitReads } from '../../apps/cockpit/src/hooks/useCockpitReads';

const snapshot: Snapshot = {
  content: [], customers: [], offers: [], rentals: [], playback: [], outbox: [],
  commands: [], campaigns: [], members: [], links: [],
};
const pages: GoldPages = {
  dashboard: {
    source: { name: 'MSFlixGold', workspace_id: 'fixture', item_id: 'fixture', views: [] },
    state: 'empty', freshness: { queried_at: '2026-10-10T12:00:00Z', published_at: null,
      publication_run_id: null, order_lines: '0' },
    commercial: [], playback: [], campaigns: [], dimensions: { customers: '0', content: '0' },
  },
  catalog: [], customers: [], offers: [], orders: [], sessions: [], campaigns: [],
  window: { orders: 6, sessions: 6, references: 10000 },
};
const gold = { pages, snapshot };
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
beforeEach(() => {
  vi.clearAllMocks();
  readers.gold.mockResolvedValue(gold);
  readers.operational.mockResolvedValue(snapshot);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('prefetches a fresh Catalog once and reuses it on navigation', async () => {
  const { result, rerender } = renderHook(({ section }) => useCockpitReads(section),
    { initialProps: { section: 'overview' } });
  await waitFor(() => expect(result.current.gold).toBe(gold));
  await act(async () => { await Promise.all([result.current.prefetch('catalog'), result.current.prefetch('catalog')]); });
  expect(readers.gold.mock.calls).toEqual([['overview'], ['catalog']]);
  expect(result.current.goldLoading).toBe(false);
  rerender({ section: 'catalog' });
  expect(result.current.gold).toBe(gold);
  expect(result.current.goldLoading).toBe(false);
  expect(readers.gold).toHaveBeenCalledTimes(2);
});

it('waits for the active read and retains only the latest queued intention', async () => {
  const active = deferred<typeof gold>();
  readers.gold.mockReturnValueOnce(active.promise);
  const { result } = renderHook(() => useCockpitReads('overview'));
  let catalog!: Promise<void>, audiences!: Promise<void>;
  act(() => { catalog = result.current.prefetch('catalog'); audiences = result.current.prefetch('audiences'); });
  expect(readers.gold.mock.calls).toEqual([['overview']]);
  await act(async () => { active.resolve(gold); await Promise.all([catalog, audiences]); });
  expect(readers.gold.mock.calls).toEqual([['overview'], ['audiences']]);
});

it('deduplicates an already running prefetch when that screen is selected', async () => {
  const { result, rerender } = renderHook(({ section }) => useCockpitReads(section),
    { initialProps: { section: 'overview' } });
  await waitFor(() => expect(result.current.gold).toBe(gold));
  const catalog = deferred<typeof gold>();
  readers.gold.mockReturnValueOnce(catalog.promise);
  let prefetched!: Promise<void>;
  await act(async () => { prefetched = result.current.prefetch('catalog'); });
  rerender({ section: 'catalog' });
  expect(result.current.goldLoading).toBe(true);
  await act(async () => { catalog.resolve(gold); await prefetched; });
  expect(readers.gold.mock.calls).toEqual([['overview'], ['catalog']]);
  expect(result.current.gold).toBe(gold);
});

it('drops queued intentions on cancellation or navigation', async () => {
  const active = deferred<typeof gold>();
  readers.gold.mockReturnValueOnce(active.promise);
  const { result, rerender } = renderHook(({ section }) => useCockpitReads(section),
    { initialProps: { section: 'overview' } });
  let prefetched!: Promise<void>;
  act(() => { prefetched = result.current.prefetch('catalog'); result.current.cancelPrefetch(); });
  rerender({ section: 'insights' });
  await act(async () => { active.resolve(gold); await prefetched; });
  expect(readers.gold.mock.calls).toEqual([['overview']]);
});

it('does not surface a failed prefetch on the active screen and retries on entry', async () => {
  const { result, rerender } = renderHook(({ section }) => useCockpitReads(section),
    { initialProps: { section: 'overview' } });
  await waitFor(() => expect(result.current.gold).toBe(gold));
  readers.gold.mockRejectedValueOnce(new Error('Catalog temporarily unavailable'));
  await act(async () => { await result.current.prefetch('catalog'); });
  expect(result.current.goldError).toBe('');
  rerender({ section: 'catalog' });
  await waitFor(() => expect(result.current.gold).toBe(gold));
  expect(result.current.goldError).toBe('');
  expect(readers.gold.mock.calls).toEqual([['overview'], ['catalog'], ['catalog']]);
});

it('revalidates prefetched data after its 30-second lifetime', async () => {
  let now = Date.parse('2026-10-10T12:00:00Z');
  vi.spyOn(Date, 'now').mockImplementation(() => now);
  const { result } = renderHook(() => useCockpitReads('overview'));
  await waitFor(() => expect(result.current.gold).toBe(gold));
  await act(async () => { await result.current.prefetch('catalog'); });
  await act(async () => { await result.current.prefetch('catalog'); });
  expect(readers.gold).toHaveBeenCalledTimes(2);
  now += 30_001;
  await act(async () => { await result.current.prefetch('catalog'); });
  expect(readers.gold).toHaveBeenCalledTimes(3);
});

it('does not preload unrelated data or preload when data saving is enabled', async () => {
  const { result } = renderHook(() => useCockpitReads('overview'));
  await waitFor(() => expect(result.current.gold).toBe(gold));
  await act(async () => { await result.current.prefetch('demo'); });
  vi.stubGlobal('navigator', { connection: { saveData: true } });
  await act(async () => { await result.current.prefetch('catalog'); });
  expect(readers.gold.mock.calls).toEqual([['overview']]);
  expect(readers.operational).not.toHaveBeenCalled();
});

it('does not publish a queued prefetch after unmount or share it with a new session', async () => {
  const active = deferred<typeof gold>();
  readers.gold.mockReturnValueOnce(active.promise);
  const first = renderHook(() => useCockpitReads('overview'));
  let prefetched!: Promise<void>;
  act(() => { prefetched = first.result.current.prefetch('catalog'); });
  first.unmount();
  await act(async () => { active.resolve(gold); await prefetched; });
  const second = renderHook(() => useCockpitReads('catalog'));
  await waitFor(() => expect(second.result.current.gold).toBe(gold));
  expect(readers.gold.mock.calls).toEqual([['overview'], ['catalog']]);
});
