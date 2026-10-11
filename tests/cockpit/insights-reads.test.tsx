import { StrictMode, type ReactNode } from 'react';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { insightsFixture } from './insights-fixture';

const load = vi.hoisted(() => vi.fn());
vi.mock('../../apps/cockpit/src/services/insights', () => ({ loadGoldInsights: load }));
import { useGoldInsights } from '../../apps/cockpit/src/hooks/useGoldInsights';
import { ReadCacheContext } from '../../apps/cockpit/src/hooks/ReadCacheContext';
import { createReadCache, type ReadCache } from '../../apps/cockpit/src/services/readCache';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
beforeEach(() => {
  localStorage.clear();
  load.mockReset();
  load.mockImplementation(async filters => insightsFixture({ filters: { ...insightsFixture().filters, ...filters } }));
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

function withCache(cache: ReadCache) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <ReadCacheContext.Provider value={cache}>{children}</ReadCacheContext.Provider>;
  };
}

describe('scoped Gold insights reads', () => {
  it('waits for activation and retains results beyond five minutes and browser focus', async () => {
    const view = renderHook(({ active }) => useGoldInsights(active, 0), { initialProps: { active: false } });
    expect(load).not.toHaveBeenCalled();
    view.rerender({ active: true });
    await waitFor(() => expect(view.result.current.data?.summary.orders).toBe(3));
    const previous = view.result.current.data;
    vi.spyOn(Date, 'now').mockReturnValue(Date.now() + 600_000);
    view.rerender({ active: false });
    view.rerender({ active: true });
    await act(async () => {
      window.dispatchEvent(new Event('focus'));
      document.dispatchEvent(new Event('visibilitychange'));
    });
    expect(load).toHaveBeenCalledTimes(1);
    expect(view.result.current.data).toBe(previous);
    expect(view.result.current.loading).toBe(false);
  });

  it('coalesces StrictMode and simultaneous identical reads', async () => {
    const initial = deferred<ReturnType<typeof insightsFixture>>();
    load.mockReturnValue(initial.promise);
    const view = renderHook(() => useGoldInsights(true, 0), {
      wrapper: ({ children }: { children: ReactNode }) => <StrictMode>{children}</StrictMode>,
    });
    act(() => { void view.result.current.apply({}); void view.result.current.apply({}); });
    await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
    await act(async () => { initial.resolve(insightsFixture()); await initial.promise; });
    expect(view.result.current.loading).toBe(false);
    expect(view.result.current.data?.summary.orders).toBe(3);
  });

  it('reuses default, partial and canonical filters without depending on property order', async () => {
    const view = renderHook(() => useGoldInsights(true, 0));
    await waitFor(() => expect(view.result.current.data).not.toBeNull());
    const defaults = view.result.current.data;
    await act(async () => { await view.result.current.apply({ territory: 'FR', currency: 'EUR' }); });
    const filtered = view.result.current.data;
    await act(async () => { await view.result.current.apply({}); });
    expect(view.result.current.data).toBe(defaults);
    await act(async () => { await view.result.current.apply({ currency: 'EUR', territory: 'FR' }); });
    expect(view.result.current.data).toBe(filtered);
    await act(async () => { await view.result.current.apply(filtered!.filters); });
    expect(load).toHaveBeenCalledTimes(2);
    expect(view.result.current.loading).toBe(false);
  });

  it.each(['button', 'refreshKey'])('%s refresh replaces the current result and invalidates other variants', async source => {
    const view = renderHook(({ refreshKey }) => useGoldInsights(true, refreshKey), { initialProps: { refreshKey: 0 } });
    await waitFor(() => expect(view.result.current.data).not.toBeNull());
    await act(async () => { await view.result.current.apply({ territory: 'FR' }); });
    const previous = view.result.current.data;
    if (source === 'button') await act(async () => { await view.result.current.refresh(); });
    else view.rerender({ refreshKey: 1 });
    await waitFor(() => expect(load).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(view.result.current.loading).toBe(false));
    expect(load).toHaveBeenLastCalledWith(previous!.filters);
    expect(view.result.current.data).not.toBe(previous);
    await act(async () => { await view.result.current.apply(view.result.current.data!.filters); });
    expect(load).toHaveBeenCalledTimes(3);
    await act(async () => { await view.result.current.apply({}); });
    expect(load).toHaveBeenCalledTimes(4);
  });

  it('retains the successful result after failed refresh and does not retry on navigation', async () => {
    const view = renderHook(({ active, refreshKey }) => useGoldInsights(active, refreshKey), { initialProps: { active: true, refreshKey: 0 } });
    await waitFor(() => expect(view.result.current.data).not.toBeNull());
    const previous = view.result.current.data;
    load.mockRejectedValueOnce(new Error('Warehouse temporarily unavailable'));
    view.rerender({ active: true, refreshKey: 1 });
    await waitFor(() => expect(view.result.current.error).toContain('Warehouse temporarily unavailable'));
    view.rerender({ active: false, refreshKey: 1 });
    view.rerender({ active: true, refreshKey: 1 });
    await act(async () => { window.dispatchEvent(new Event('focus')); });
    expect(load).toHaveBeenCalledTimes(2);
    expect(view.result.current.data).toBe(previous);
    expect(load).toHaveBeenLastCalledWith(previous!.filters);
    await act(async () => { await view.result.current.refresh(); });
    expect(load).toHaveBeenCalledTimes(3);
    expect(view.result.current.error).toBe('');
  });

  it('keeps server validation errors and only explicitly retries the failed selection', async () => {
    const view = renderHook(({ active }) => useGoldInsights(active, 0), { initialProps: { active: true } });
    await waitFor(() => expect(view.result.current.data).not.toBeNull());
    load.mockRejectedValueOnce(new Error('Invalid analysis date range'));
    const filters = { from: 'invalid-date', territory: 'GB', currency: 'GBP' };
    await act(async () => { await view.result.current.apply(filters); });
    expect(load).toHaveBeenLastCalledWith(filters);
    expect(view.result.current.data?.filters.currency).toBe('EUR');
    expect(view.result.current.error).toContain('Invalid analysis date range');
    view.rerender({ active: false });
    view.rerender({ active: true });
    await act(async () => { await view.result.current.apply({ currency: 'GBP', territory: 'GB', from: 'invalid-date' }); });
    expect(load).toHaveBeenCalledTimes(2);
    await act(async () => { await view.result.current.refresh(); });
    expect(load).toHaveBeenCalledTimes(3);
    expect(load).toHaveBeenLastCalledWith(filters);
  });

  it('discards a late result from an older filter selection', async () => {
    const older = deferred<ReturnType<typeof insightsFixture>>();
    const newer = deferred<ReturnType<typeof insightsFixture>>();
    load.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
    const view = renderHook(() => useGoldInsights(true, 0));
    act(() => { void view.result.current.apply({ territory: 'FR' }); });
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    const filtered = insightsFixture({ filters: { ...insightsFixture().filters, territory: 'FR' } });
    await act(async () => { newer.resolve(filtered); await newer.promise; });
    await act(async () => { older.resolve(insightsFixture()); await older.promise; });
    expect(view.result.current.data).toBe(filtered);
    expect(view.result.current.loading).toBe(false);
  });

  it('keeps explicit refresh requests dormant while hidden', async () => {
    const view = renderHook(({ active, refreshKey }) => useGoldInsights(active, refreshKey), { initialProps: { active: true, refreshKey: 0 } });
    await waitFor(() => expect(view.result.current.data).not.toBeNull());
    view.rerender({ active: false, refreshKey: 1 });
    await act(async () => { await view.result.current.refresh(); });
    expect(load).toHaveBeenCalledTimes(1);
    view.rerender({ active: true, refreshKey: 1 });
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
  });

  it('reloads the current selection after command invalidation, but only when active', async () => {
    const cache = createReadCache();
    const view = renderHook(({ active }) => useGoldInsights(active, 0), { initialProps: { active: true }, wrapper: withCache(cache) });
    await waitFor(() => expect(view.result.current.data).not.toBeNull());
    await act(async () => { await view.result.current.apply({ territory: 'FR' }); });
    const filters = view.result.current.data!.filters;
    act(() => cache.invalidate('read:'));
    await waitFor(() => expect(load).toHaveBeenCalledTimes(3));
    expect(load).toHaveBeenLastCalledWith(filters);
    await waitFor(() => expect(view.result.current.loading).toBe(false));
    view.rerender({ active: false });
    act(() => cache.invalidate('read:'));
    expect(cache.get('ui:insights:selection')).toEqual(filters);
    expect(load).toHaveBeenCalledTimes(3);
    view.rerender({ active: true });
    await waitFor(() => expect(load).toHaveBeenCalledTimes(4));
    expect(load).toHaveBeenLastCalledWith(filters);
  });

  it.each(['command', 'refresh'])('fences an older pending response after %s invalidation', async source => {
    const cache = createReadCache();
    const older = deferred<ReturnType<typeof insightsFixture>>();
    const newer = deferred<ReturnType<typeof insightsFixture>>();
    load.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
    const view = renderHook(() => useGoldInsights(true, 0), { wrapper: withCache(cache) });
    await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
    act(() => { if (source === 'command') cache.invalidate('read:'); else void view.result.current.refresh(); });
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    await act(async () => { older.resolve(insightsFixture()); await older.promise; });
    expect(view.result.current.data).toBeNull();
    expect(view.result.current.loading).toBe(true);
    expect(cache.get('ui:insights:selection')).toBeUndefined();
    const updated = insightsFixture({ summary: { ...insightsFixture().summary, orders: 9 } });
    await act(async () => { newer.resolve(updated); await newer.promise; });
    expect(view.result.current.data).toBe(updated);
    await act(async () => { await view.result.current.apply({}); });
    expect(view.result.current.data).toBe(updated);
    expect(load).toHaveBeenCalledTimes(2);
  });

  it('does not show an invalidated response while the section is hidden', async () => {
    const cache = createReadCache();
    const older = deferred<ReturnType<typeof insightsFixture>>();
    load.mockReturnValueOnce(older.promise);
    const view = renderHook(({ active }) => useGoldInsights(active, 0), { initialProps: { active: true }, wrapper: withCache(cache) });
    await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
    view.rerender({ active: false });
    act(() => cache.invalidate('read:'));
    await act(async () => { older.resolve(insightsFixture()); await older.promise; });
    expect(view.result.current.data).toBeNull();
    expect(load).toHaveBeenCalledTimes(1);
    view.rerender({ active: true });
    await waitFor(() => expect(view.result.current.data).not.toBeNull());
    expect(load).toHaveBeenCalledTimes(2);
  });

  it('does not let an unmounted selection replace the last successful preference', async () => {
    const cache = createReadCache('insights-unmount');
    const view = renderHook(() => useGoldInsights(true, 0), { wrapper: withCache(cache) });
    await waitFor(() => expect(view.result.current.data).not.toBeNull());
    const previous = view.result.current.data;
    const pending = deferred<ReturnType<typeof insightsFixture>>();
    load.mockReturnValueOnce(pending.promise);
    act(() => { void view.result.current.apply({ territory: 'FR' }); });
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    view.unmount();
    await act(async () => { pending.resolve(insightsFixture({ filters: { ...previous!.filters, territory: 'FR' } })); await pending.promise; });
    const restored = renderHook(() => useGoldInsights(true, 0), { wrapper: withCache(createReadCache('insights-unmount')) });
    expect(restored.result.current.data).toEqual(previous);
    expect(load).toHaveBeenCalledTimes(2);
  });

  it('restores a filtered selection and its variants from a new cache provider without loading', async () => {
    const namespace = 'insights-user-a-workspace-a';
    const view = renderHook(() => useGoldInsights(true, 0), { wrapper: withCache(createReadCache(namespace)) });
    await waitFor(() => expect(view.result.current.data).not.toBeNull());
    const defaults = view.result.current.data;
    await act(async () => { await view.result.current.apply({ territory: 'FR', currency: 'EUR' }); });
    const filtered = view.result.current.data;
    view.unmount();
    const restored = renderHook(() => useGoldInsights(true, 0), { wrapper: withCache(createReadCache(namespace)) });
    expect(restored.result.current.data).toEqual(filtered);
    expect(restored.result.current.loading).toBe(false);
    await act(async () => { await restored.result.current.apply({}); });
    expect(restored.result.current.data).toEqual(defaults);
    await act(async () => { await restored.result.current.apply({ currency: 'EUR', territory: 'FR' }); });
    expect(restored.result.current.data).toEqual(filtered);
    expect(load).toHaveBeenCalledTimes(2);
  });

  it.each(['insights-user-b-workspace-a', 'insights-user-a-workspace-b'])('never shares selection or data with %s', async namespace => {
    let cache = createReadCache('insights-user-a-workspace-a');
    const view = renderHook(() => useGoldInsights(true, 0), {
      wrapper: ({ children }: { children: ReactNode }) => <ReadCacheContext.Provider value={cache}>{children}</ReadCacheContext.Provider>,
    });
    await waitFor(() => expect(view.result.current.data).not.toBeNull());
    await act(async () => { await view.result.current.apply({ territory: 'FR' }); });
    const other = deferred<ReturnType<typeof insightsFixture>>();
    load.mockReturnValueOnce(other.promise);
    cache = createReadCache(namespace);
    view.rerender();
    expect(view.result.current.data).toBeNull();
    await waitFor(() => expect(load).toHaveBeenCalledTimes(3));
    expect(load).toHaveBeenLastCalledWith({});
    await act(async () => { other.resolve(insightsFixture()); await other.promise; });
    expect(view.result.current.data?.filters.territory).toBe('');
  });

  it('does not retry a failed first read on navigation or a repeated Apply', async () => {
    load.mockRejectedValueOnce(new Error('Initial Gold read unavailable'));
    const view = renderHook(({ active }) => useGoldInsights(active, 0), { initialProps: { active: true } });
    await waitFor(() => expect(view.result.current.error).toContain('Initial Gold read unavailable'));
    view.rerender({ active: false });
    view.rerender({ active: true });
    await act(async () => { await view.result.current.apply({}); });
    expect(load).toHaveBeenCalledTimes(1);
    expect(view.result.current.data).toBeNull();
    expect(view.result.current.loading).toBe(false);
    await act(async () => { await view.result.current.refresh(); });
    expect(load).toHaveBeenCalledTimes(2);
    expect(view.result.current.data).not.toBeNull();
  });

  it('leaves its cached view unchanged when another read namespace is invalidated', async () => {
    const cache = createReadCache();
    const view = renderHook(() => useGoldInsights(true, 0), { wrapper: withCache(cache) });
    await waitFor(() => expect(view.result.current.data).not.toBeNull());
    const previous = view.result.current.data;
    await act(async () => { cache.invalidate('read:campaign:'); });
    expect(view.result.current.data).toBe(previous);
    expect(view.result.current.loading).toBe(false);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('cannot apply an old identity response after a provider switch', async () => {
    let cache = createReadCache('old-insights-user');
    const oldIdentity = deferred<ReturnType<typeof insightsFixture>>();
    const newIdentity = deferred<ReturnType<typeof insightsFixture>>();
    load.mockReturnValueOnce(oldIdentity.promise).mockReturnValueOnce(newIdentity.promise);
    const view = renderHook(() => useGoldInsights(true, 0), {
      wrapper: ({ children }: { children: ReactNode }) => <ReadCacheContext.Provider value={cache}>{children}</ReadCacheContext.Provider>,
    });
    await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
    cache = createReadCache('new-insights-user');
    view.rerender();
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    await act(async () => { oldIdentity.resolve(insightsFixture()); await oldIdentity.promise; });
    expect(view.result.current.data).toBeNull();
    expect(cache.get('ui:insights:selection')).toBeUndefined();
    const current = insightsFixture({ summary: { ...insightsFixture().summary, orders: 9 } });
    await act(async () => { newIdentity.resolve(current); await newIdentity.promise; });
    expect(view.result.current.data).toBe(current);
  });

  it.each([null, ['FR'], { territory: 7 }])('ignores a malformed saved filter preference: %j', async preference => {
    const cache = createReadCache('insights-malformed');
    cache.set('ui:insights:selection', preference);
    const view = renderHook(() => useGoldInsights(true, 0), { wrapper: withCache(createReadCache('insights-malformed')) });
    await waitFor(() => expect(view.result.current.data).not.toBeNull());
    expect(load).toHaveBeenCalledTimes(1);
    expect(load).toHaveBeenLastCalledWith({});
    expect(view.result.current.error).toBe('');
  });
});
