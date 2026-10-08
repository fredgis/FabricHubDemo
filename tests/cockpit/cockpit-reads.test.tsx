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
afterEach(cleanup);

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
