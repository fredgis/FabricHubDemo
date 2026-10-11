import { StrictMode, type ReactNode } from 'react';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { campaignImpactFixture } from './campaign-impact-fixture';

const load = vi.hoisted(() => vi.fn());
vi.mock('../../apps/cockpit/src/services/campaignImpact', () => ({ loadCampaignImpact: load }));
import { useCampaignImpact } from '../../apps/cockpit/src/hooks/useCampaignImpact';
import { ReadCacheContext } from '../../apps/cockpit/src/hooks/ReadCacheContext';
import { createReadCache, type ReadCache } from '../../apps/cockpit/src/services/readCache';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
beforeEach(() => {
  localStorage.clear();
  load.mockReset();
  load.mockImplementation(async filters => campaignImpactFixture({ filters: { ...campaignImpactFixture().filters, ...filters } }));
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

it('waits for activation, retains results beyond five minutes and ignores browser focus', async () => {
  const view = renderHook(({ active }) => useCampaignImpact(active, 0), { initialProps: { active: false } });
  expect(load).not.toHaveBeenCalled();
  view.rerender({ active: true });
  await waitFor(() => expect(view.result.current.data?.summary.contacted_customers).toBe(600));
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

it('coalesces StrictMode and identical requests with reordered filter properties', async () => {
  const initial = deferred<ReturnType<typeof campaignImpactFixture>>();
  load.mockReturnValue(initial.promise);
  const view = renderHook(() => useCampaignImpact(true, 0), { wrapper: ({ children }: { children: ReactNode }) => <StrictMode>{children}</StrictMode> });
  act(() => { void view.result.current.apply({}); void view.result.current.apply({}); });
  await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
  await act(async () => { initial.resolve(campaignImpactFixture()); await initial.promise; });
  const filtered = deferred<ReturnType<typeof campaignImpactFixture>>();
  load.mockReturnValueOnce(filtered.promise);
  act(() => {
    void view.result.current.apply({ currency: 'JPY', territory: 'US' });
    void view.result.current.apply({ territory: 'US', currency: 'JPY' });
  });
  await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
  await act(async () => {
    filtered.resolve(campaignImpactFixture({ filters: { ...campaignImpactFixture().filters, currency: 'JPY', territory: 'US' } }));
    await filtered.promise;
  });
  expect(view.result.current.loading).toBe(false);
  expect(view.result.current.data?.summary.engaged_per_100_minor).toBe('0');
});

it('reuses cached modes, campaigns and canonical filters independently of property order', async () => {
  const view = renderHook(() => useCampaignImpact(true, 0));
  await waitFor(() => expect(view.result.current.data).not.toBeNull());
  const defaults = view.result.current.data;
  await act(async () => { await view.result.current.apply({ analysisMode: 'post_contact', currency: 'JPY', campaignKey: 'test-campaign-2' }); });
  const filtered = view.result.current.data;
  await act(async () => { await view.result.current.apply({}); });
  expect(view.result.current.data).toBe(defaults);
  await act(async () => { await view.result.current.apply({ campaignKey: 'test-campaign-2', currency: 'JPY', analysisMode: 'post_contact' }); });
  expect(view.result.current.data).toBe(filtered);
  await act(async () => { await view.result.current.apply(filtered!.filters); });
  expect(load).toHaveBeenCalledTimes(2);
  expect(view.result.current.loading).toBe(false);
});

it.each(['button', 'refreshKey'])('%s refresh replaces the current campaign result and invalidates other variants', async source => {
  const view = renderHook(({ refreshKey }) => useCampaignImpact(true, refreshKey), { initialProps: { refreshKey: 0 } });
  await waitFor(() => expect(view.result.current.data).not.toBeNull());
  await act(async () => { await view.result.current.apply({ currency: 'JPY' }); });
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

it('preserves previous data after failed refresh and retries only on explicit request', async () => {
  const view = renderHook(({ active, refreshKey }) => useCampaignImpact(active, refreshKey), { initialProps: { active: true, refreshKey: 0 } });
  await waitFor(() => expect(view.result.current.data).not.toBeNull());
  const previous = view.result.current.data;
  load.mockRejectedValueOnce(new Error('Temporary Gold failure'));
  view.rerender({ active: true, refreshKey: 1 });
  await waitFor(() => expect(view.result.current.error).toContain('Temporary Gold failure'));
  view.rerender({ active: false, refreshKey: 1 });
  view.rerender({ active: true, refreshKey: 1 });
  await act(async () => { window.dispatchEvent(new Event('focus')); });
  expect(load).toHaveBeenCalledTimes(2);
  expect(view.result.current.data).toBe(previous);
  await act(async () => { await view.result.current.refresh(); });
  expect(load).toHaveBeenCalledTimes(3);
  expect(load).toHaveBeenLastCalledWith(previous!.filters);
  expect(view.result.current.error).toBe('');
});

it('preserves server validation and retries the failed selection rather than the last success', async () => {
  const view = renderHook(({ active }) => useCampaignImpact(active, 0), { initialProps: { active: true } });
  await waitFor(() => expect(view.result.current.data).not.toBeNull());
  const previous = view.result.current.data;
  load.mockRejectedValueOnce(new Error('Invalid campaign currency'));
  const filters = { territory: 'US', currency: 'invalid' };
  await act(async () => { await view.result.current.apply(filters); });
  expect(view.result.current.data).toBe(previous);
  expect(view.result.current.error).toContain('Invalid campaign currency');
  expect(load).toHaveBeenLastCalledWith(filters);
  view.rerender({ active: false });
  view.rerender({ active: true });
  await act(async () => { await view.result.current.apply({ currency: 'invalid', territory: 'US' }); });
  expect(load).toHaveBeenCalledTimes(2);
  await act(async () => { await view.result.current.refresh(); });
  expect(load).toHaveBeenCalledTimes(3);
  expect(load).toHaveBeenLastCalledWith(filters);
});

it('ignores a late response from an older currency selection', async () => {
  const older = deferred<ReturnType<typeof campaignImpactFixture>>();
  const newer = deferred<ReturnType<typeof campaignImpactFixture>>();
  load.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
  const view = renderHook(() => useCampaignImpact(true, 0));
  act(() => { void view.result.current.apply({ currency: 'JPY' }); });
  await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
  const filtered = campaignImpactFixture({ filters: { ...campaignImpactFixture().filters, currency: 'JPY' } });
  await act(async () => { newer.resolve(filtered); await newer.promise; });
  await act(async () => { older.resolve(campaignImpactFixture()); await older.promise; });
  expect(view.result.current.data).toBe(filtered);
  expect(view.result.current.loading).toBe(false);
  expect(view.result.current.error).toBe('');
});

it('keeps refreshes dormant while hidden, including a direct refresh request', async () => {
  const view = renderHook(({ active, refreshKey }) => useCampaignImpact(active, refreshKey), { initialProps: { active: true, refreshKey: 0 } });
  await waitFor(() => expect(view.result.current.data).not.toBeNull());
  view.rerender({ active: false, refreshKey: 1 });
  await act(async () => { await view.result.current.refresh(); });
  expect(load).toHaveBeenCalledTimes(1);
  view.rerender({ active: true, refreshKey: 1 });
  await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
  expect(load).toHaveBeenLastCalledWith(campaignImpactFixture().filters);
});

it('reloads after commands without fetching inactive campaign panels', async () => {
  const cache = createReadCache();
  const view = renderHook(({ active }) => useCampaignImpact(active, 0), { initialProps: { active: true }, wrapper: withCache(cache) });
  await waitFor(() => expect(view.result.current.data).not.toBeNull());
  await act(async () => { await view.result.current.apply({ currency: 'JPY' }); });
  const filters = view.result.current.data!.filters;
  act(() => cache.invalidate('read:'));
  await waitFor(() => expect(load).toHaveBeenCalledTimes(3));
  expect(load).toHaveBeenLastCalledWith(filters);
  await waitFor(() => expect(view.result.current.loading).toBe(false));
  view.rerender({ active: false });
  act(() => cache.invalidate('read:'));
  expect(cache.get('ui:campaign:selection')).toEqual(filters);
  expect(load).toHaveBeenCalledTimes(3);
  view.rerender({ active: true });
  await waitFor(() => expect(load).toHaveBeenCalledTimes(4));
  expect(load).toHaveBeenLastCalledWith(filters);
});

it.each(['command', 'refresh'])('fences an old campaign response after %s invalidation', async source => {
  const cache = createReadCache();
  const older = deferred<ReturnType<typeof campaignImpactFixture>>();
  const newer = deferred<ReturnType<typeof campaignImpactFixture>>();
  load.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
  const view = renderHook(() => useCampaignImpact(true, 0), { wrapper: withCache(cache) });
  await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
  act(() => { if (source === 'command') cache.invalidate('read:'); else void view.result.current.refresh(); });
  await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
  await act(async () => { older.resolve(campaignImpactFixture()); await older.promise; });
  expect(view.result.current.data).toBeNull();
  expect(view.result.current.loading).toBe(true);
  expect(cache.get('ui:campaign:selection')).toBeUndefined();
  const updated = campaignImpactFixture({ summary: { ...campaignImpactFixture().summary, contacted_customers: 900 } });
  await act(async () => { newer.resolve(updated); await newer.promise; });
  expect(view.result.current.data).toBe(updated);
  await act(async () => { await view.result.current.apply({}); });
  expect(view.result.current.data).toBe(updated);
  expect(load).toHaveBeenCalledTimes(2);
});

it('cannot restore an invalidated pending result in a hidden panel', async () => {
  const cache = createReadCache();
  const older = deferred<ReturnType<typeof campaignImpactFixture>>();
  load.mockReturnValueOnce(older.promise);
  const view = renderHook(({ active }) => useCampaignImpact(active, 0), { initialProps: { active: true }, wrapper: withCache(cache) });
  await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
  view.rerender({ active: false });
  act(() => cache.invalidate('read:'));
  await act(async () => { older.resolve(campaignImpactFixture()); await older.promise; });
  expect(view.result.current.data).toBeNull();
  expect(load).toHaveBeenCalledTimes(1);
  view.rerender({ active: true });
  await waitFor(() => expect(view.result.current.data).not.toBeNull());
  expect(load).toHaveBeenCalledTimes(2);
});

it('does not persist a selection that finishes after unmount', async () => {
  const cache = createReadCache('campaign-unmount');
  const view = renderHook(() => useCampaignImpact(true, 0), { wrapper: withCache(cache) });
  await waitFor(() => expect(view.result.current.data).not.toBeNull());
  const previous = view.result.current.data;
  const pending = deferred<ReturnType<typeof campaignImpactFixture>>();
  load.mockReturnValueOnce(pending.promise);
  act(() => { void view.result.current.apply({ currency: 'JPY' }); });
  await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
  view.unmount();
  await act(async () => { pending.resolve(campaignImpactFixture({ filters: { ...previous!.filters, currency: 'JPY' } })); await pending.promise; });
  const restored = renderHook(() => useCampaignImpact(true, 0), { wrapper: withCache(createReadCache('campaign-unmount')) });
  expect(restored.result.current.data).toEqual(previous);
  expect(load).toHaveBeenCalledTimes(2);
});

it('restores the last campaign filters and cached variants through a new provider', async () => {
  const namespace = 'campaign-user-a-workspace-a';
  const view = renderHook(() => useCampaignImpact(true, 0), { wrapper: withCache(createReadCache(namespace)) });
  await waitFor(() => expect(view.result.current.data).not.toBeNull());
  const defaults = view.result.current.data;
  await act(async () => { await view.result.current.apply({ currency: 'JPY', analysisMode: 'post_contact', campaignKey: 'test-campaign-2' }); });
  const filtered = view.result.current.data;
  view.unmount();
  const restored = renderHook(() => useCampaignImpact(true, 0), { wrapper: withCache(createReadCache(namespace)) });
  expect(restored.result.current.data).toEqual(filtered);
  expect(restored.result.current.loading).toBe(false);
  await act(async () => { await restored.result.current.apply({}); });
  expect(restored.result.current.data).toEqual(defaults);
  await act(async () => { await restored.result.current.apply({ campaignKey: 'test-campaign-2', analysisMode: 'post_contact', currency: 'JPY' }); });
  expect(restored.result.current.data).toEqual(filtered);
  expect(load).toHaveBeenCalledTimes(2);
});

it.each(['campaign-user-b-workspace-a', 'campaign-user-a-workspace-b'])('isolates both preferences and data from %s', async namespace => {
  let cache = createReadCache('campaign-user-a-workspace-a');
  const view = renderHook(() => useCampaignImpact(true, 0), {
    wrapper: ({ children }: { children: ReactNode }) => <ReadCacheContext.Provider value={cache}>{children}</ReadCacheContext.Provider>,
  });
  await waitFor(() => expect(view.result.current.data).not.toBeNull());
  await act(async () => { await view.result.current.apply({ currency: 'JPY' }); });
  const other = deferred<ReturnType<typeof campaignImpactFixture>>();
  load.mockReturnValueOnce(other.promise);
  cache = createReadCache(namespace);
  view.rerender();
  expect(view.result.current.data).toBeNull();
  await waitFor(() => expect(load).toHaveBeenCalledTimes(3));
  expect(load).toHaveBeenLastCalledWith({});
  await act(async () => { other.resolve(campaignImpactFixture()); await other.promise; });
  expect(view.result.current.data?.filters.currency).toBe('EUR');
});

it('does not retry a failed first campaign read until explicit Refresh', async () => {
  load.mockRejectedValueOnce(new Error('Initial campaign read unavailable'));
  const view = renderHook(({ active }) => useCampaignImpact(active, 0), { initialProps: { active: true } });
  await waitFor(() => expect(view.result.current.error).toContain('Initial campaign read unavailable'));
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

it('keeps cached campaign data stable through unrelated invalidations', async () => {
  const cache = createReadCache();
  const view = renderHook(() => useCampaignImpact(true, 0), { wrapper: withCache(cache) });
  await waitFor(() => expect(view.result.current.data).not.toBeNull());
  const previous = view.result.current.data;
  await act(async () => { cache.invalidate('read:insights:'); });
  expect(view.result.current.data).toBe(previous);
  expect(view.result.current.loading).toBe(false);
  expect(load).toHaveBeenCalledTimes(1);
});

it.each([null, ['JPY'], { currency: 7 }])('ignores a malformed saved campaign selection: %j', async preference => {
  const cache = createReadCache('campaign-malformed');
  cache.set('ui:campaign:selection', preference);
  const view = renderHook(() => useCampaignImpact(true, 0), { wrapper: withCache(createReadCache('campaign-malformed')) });
  await waitFor(() => expect(view.result.current.data).not.toBeNull());
  expect(load).toHaveBeenCalledTimes(1);
  expect(load).toHaveBeenLastCalledWith({});
  expect(view.result.current.error).toBe('');
});
