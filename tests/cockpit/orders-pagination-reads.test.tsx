import type { ReactNode } from 'react';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { OrdersReadOptions, Snapshot } from '../../apps/cockpit/src/services/business';

const read = vi.hoisted(() => vi.fn());
vi.mock('../../apps/cockpit/src/services/business', () => ({ loadSnapshot: read, safeError: (error: Error) => error.message }));
vi.mock('../../apps/cockpit/src/services/goldViews', () => ({ loadGoldViews: vi.fn() }));
import { useCockpitReads } from '../../apps/cockpit/src/hooks/useCockpitReads';
import { ReadCacheContext } from '../../apps/cockpit/src/hooks/ReadCacheContext';
import { createReadCache } from '../../apps/cockpit/src/services/readCache';
const withCache = (namespace: string) => {
  const cache = createReadCache(namespace);
  return ({ children }: { children: ReactNode }) => <ReadCacheContext.Provider value={cache}>{children}</ReadCacheContext.Provider>;
};

function page(ordersPage = 1, playbackPage = 1, ordersTotal = 151, playbackTotal = 101): Snapshot {
  return {
    content: [], customers: [], offers: [], rentals: [], playback: [], outbox: [],
    commands: [], campaigns: [], members: [], links: [],
    pagination: { orders: { page: ordersPage, pageSize: 50, total: ordersTotal },
      sessions: { page: playbackPage, pageSize: 50, total: playbackTotal } },
  };
}
function deferred() {
  let resolve!: (value: Snapshot) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<Snapshot>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
beforeEach(() => {
  read.mockReset();
  read.mockImplementation(async (_scope: string, options: OrdersReadOptions) => page(options.ordersPage, options.playbackPage));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it('keeps pages independent and reuses reference data until explicit refresh', async () => {
  let now = Date.parse('2026-10-11T08:00:00Z');
  vi.spyOn(Date, 'now').mockImplementation(() => now);
  const { result } = renderHook(() => useCockpitReads('orders'));
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(read).toHaveBeenLastCalledWith('orders', { ordersPage: 1, playbackPage: 1 });
  const first = result.current.snapshot!;
  const references = { content: first.content, customers: first.customers, offers: first.offers };
  now += 20_000;
  act(() => { result.current.setOrderPages(current => ({ ...current, ordersPage: 2 })); });
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(read).toHaveBeenLastCalledWith('orders', { ordersPage: 2, playbackPage: 1, references });
  now += 6 * 60_000;
  act(() => { result.current.setOrderPages(current => ({ ...current, playbackPage: 2 })); });
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(read).toHaveBeenLastCalledWith('orders', { ordersPage: 2, playbackPage: 2, references });
  await act(async () => { await result.current.refresh(); });
  expect(read).toHaveBeenLastCalledWith('orders', { ordersPage: 2, playbackPage: 2 });
  expect(read).toHaveBeenCalledTimes(4);
});

it('keeps the last page during a read and an error, then retries the requested page with fresh references', async () => {
  const { result } = renderHook(() => useCockpitReads('orders'));
  await waitFor(() => expect(result.current.loading).toBe(false));
  const first = result.current.snapshot;
  const updated = result.current.updated;
  const next = deferred();
  read.mockReturnValueOnce(next.promise);
  act(() => { result.current.setOrderPages({ ordersPage: 2, playbackPage: 1 }); });
  expect(result.current.loading).toBe(true);
  expect(result.current.snapshot).toBe(first);
  await act(async () => { next.reject(new Error('Fixture page unavailable')); });
  expect(result.current.snapshot).toBe(first);
  expect(result.current.updated).toBe(updated);
  expect(result.current.error).toBe('Fixture page unavailable');
  expect(result.current.loading).toBe(false);
  await act(async () => { await result.current.refresh(); });
  expect(read).toHaveBeenLastCalledWith('orders', { ordersPage: 2, playbackPage: 1 });
  expect(result.current.snapshot?.pagination?.orders.page).toBe(2);
  expect(result.current.error).toBe('');
});

it.each(['success', 'failure'])('ignores the %s of an older page after a newer page finishes', async outcome => {
  const { result } = renderHook(() => useCockpitReads('orders'));
  await waitFor(() => expect(result.current.loading).toBe(false));
  const second = deferred();
  const third = deferred();
  read.mockReturnValueOnce(second.promise).mockReturnValueOnce(third.promise);
  act(() => { result.current.setOrderPages({ ordersPage: 2, playbackPage: 1 }); });
  act(() => { result.current.setOrderPages({ ordersPage: 3, playbackPage: 1 }); });
  const authoritative = page(3);
  await act(async () => { third.resolve(authoritative); });
  const updated = result.current.updated;
  await act(async () => {
    if (outcome === 'success') second.resolve(page(2));
    else second.reject(new Error('Obsolete page failed'));
  });
  expect(result.current.snapshot).toBe(authoritative);
  expect(result.current.updated).toBe(updated);
  expect(result.current.error).toBe('');
  expect(result.current.loading).toBe(false);
});

it('accepts server-clamped pages once and keeps the clamped order page when paging playback', async () => {
  const { result } = renderHook(() => useCockpitReads('orders'));
  await waitFor(() => expect(result.current.loading).toBe(false));
  read.mockResolvedValueOnce(page(2, 1, 51));
  act(() => { result.current.setOrderPages({ ordersPage: 4, playbackPage: 1 }); });
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.snapshot?.pagination?.orders).toEqual({ page: 2, pageSize: 50, total: 51 });
  expect(read).toHaveBeenCalledTimes(2);
  act(() => { result.current.setOrderPages(current => ({ ...current, playbackPage: 2 })); });
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(read.mock.calls.at(-1)?.[1]).toMatchObject({ ordersPage: 2, playbackPage: 2 });
});

it('handles data shrinking to empty without a repeat read or a permanent loading state', async () => {
  const { result } = renderHook(() => useCockpitReads('orders'));
  await waitFor(() => expect(result.current.loading).toBe(false));
  read.mockResolvedValueOnce(page(1, 1, 0, 0));
  act(() => { result.current.setOrderPages({ ordersPage: 4, playbackPage: 3 }); });
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.snapshot?.pagination).toEqual(page(1, 1, 0, 0).pagination);
  expect(read).toHaveBeenCalledTimes(2);
});

it('does not refresh a disposed identity and gives a new identity fresh pages and references', async () => {
  const first = renderHook(() => useCockpitReads('orders'));
  await waitFor(() => expect(first.result.current.loading).toBe(false));
  act(() => { first.result.current.setOrderPages({ ordersPage: 2, playbackPage: 2 }); });
  await waitFor(() => expect(first.result.current.loading).toBe(false));
  const oldRefresh = first.result.current.refresh;
  first.unmount();
  await oldRefresh();
  expect(read).toHaveBeenCalledTimes(2);
  const second = renderHook(() => useCockpitReads('orders'));
  await waitFor(() => expect(second.result.current.loading).toBe(false));
  expect(read).toHaveBeenLastCalledWith('orders', { ordersPage: 1, playbackPage: 1 });
  expect(read).toHaveBeenCalledTimes(3);
});

it('restores the last page after remount and reuses every previously loaded page', async () => {
  const first = renderHook(() => useCockpitReads('orders'), { wrapper: withCache('orders-user') });
  await waitFor(() => expect(first.result.current.loading).toBe(false));
  act(() => { first.result.current.setOrderPages({ ordersPage: 2, playbackPage: 2 }); });
  await waitFor(() => expect(first.result.current.loading).toBe(false));
  const updated = first.result.current.updated;
  first.unmount();
  const restored = renderHook(() => useCockpitReads('orders'), { wrapper: withCache('orders-user') });
  expect(restored.result.current.snapshot?.pagination?.orders.page).toBe(2);
  expect(restored.result.current.snapshot?.pagination?.sessions.page).toBe(2);
  expect(restored.result.current.updated).toEqual(updated);
  expect(restored.result.current.loading).toBe(false);
  expect(read).toHaveBeenCalledTimes(2);
  act(() => { restored.result.current.setOrderPages({ ordersPage: 1, playbackPage: 1 }); });
  expect(restored.result.current.snapshot?.pagination?.orders.page).toBe(1);
  expect(restored.result.current.loading).toBe(false);
  expect(read).toHaveBeenCalledTimes(2);
  await act(async () => { await restored.result.current.refresh(); });
  act(() => { restored.result.current.setOrderPages({ ordersPage: 2, playbackPage: 2 }); });
  await waitFor(() => expect(restored.result.current.loading).toBe(false));
  expect(read).toHaveBeenCalledTimes(4);
});
