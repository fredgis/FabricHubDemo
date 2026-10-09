import { StrictMode, type ReactNode } from 'react';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { insightsFixture } from './insights-fixture';

const load = vi.hoisted(() => vi.fn());
vi.mock('../../apps/cockpit/src/services/insights', () => ({ loadGoldInsights: load }));
import { useGoldInsights } from '../../apps/cockpit/src/hooks/useGoldInsights';

afterEach(cleanup);
beforeEach(() => { load.mockReset(); load.mockResolvedValue(insightsFixture()); });

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

describe('scoped Gold insights reads', () => {
  it('does not query until the section is active and reuses a recent result on revisit', async () => {
    const view = renderHook(({ active }) => useGoldInsights(active, 0), { initialProps: { active: false } });
    expect(load).not.toHaveBeenCalled();
    view.rerender({ active: true });
    await waitFor(() => expect(view.result.current.data?.summary.orders).toBe(3));
    view.rerender({ active: false });
    view.rerender({ active: true });
    expect(load).toHaveBeenCalledTimes(1);
  });
  it('coalesces StrictMode and simultaneous identical reads', async () => {
    const initial = deferred<ReturnType<typeof insightsFixture>>();
    load.mockReturnValue(initial.promise);
    const view = renderHook(() => useGoldInsights(true, 0), {
      wrapper: ({ children }: { children: ReactNode }) => <StrictMode>{children}</StrictMode>,
    });
    act(() => { void view.result.current.refresh(); void view.result.current.apply({}); });
    expect(load).toHaveBeenCalledTimes(1);
    await act(async () => { initial.resolve(insightsFixture()); await initial.promise; });
    expect(view.result.current.loading).toBe(false);
  });
  it('retains the successful result if an explicit refresh fails', async () => {
    const view = renderHook(({ refreshKey }) => useGoldInsights(true, refreshKey), { initialProps: { refreshKey: 0 } });
    await waitFor(() => expect(view.result.current.data).not.toBeNull());
    const previous = view.result.current.data;
    load.mockRejectedValueOnce(new Error('Warehouse temporarily unavailable'));
    view.rerender({ refreshKey: 1 });
    await waitFor(() => expect(view.result.current.error).toContain('Warehouse temporarily unavailable'));
    expect(view.result.current.data).toBe(previous);
    expect(load).toHaveBeenLastCalledWith(previous!.filters);
  });
  it('discards a late result from an older filter selection', async () => {
    const older = deferred<ReturnType<typeof insightsFixture>>();
    const newer = deferred<ReturnType<typeof insightsFixture>>();
    load.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
    const view = renderHook(() => useGoldInsights(true, 0));
    act(() => { void view.result.current.apply({ territory: 'FR' }); });
    const filtered = insightsFixture({ filters: { ...insightsFixture().filters, territory: 'FR' } });
    await act(async () => { newer.resolve(filtered); await newer.promise; });
    await act(async () => { older.resolve(insightsFixture()); await older.promise; });
    expect(view.result.current.data?.filters.territory).toBe('FR');
    expect(view.result.current.loading).toBe(false);
  });
  it('retries the failed filter request rather than silently returning to the old selection', async () => {
    const view = renderHook(() => useGoldInsights(true, 0));
    await waitFor(() => expect(view.result.current.data).not.toBeNull());
    load.mockRejectedValueOnce(new Error('Transient read failure'));
    await act(async () => { await view.result.current.apply({ territory: 'GB', currency: 'GBP' }); });
    expect(view.result.current.data?.filters.currency).toBe('EUR');
    await act(async () => { await view.result.current.refresh(); });
    expect(load).toHaveBeenLastCalledWith({ territory: 'GB', currency: 'GBP' });
  });
  it('keeps refresh requests dormant while hidden', async () => {
    const view = renderHook(({ active, refreshKey }) => useGoldInsights(active, refreshKey), { initialProps: { active: true, refreshKey: 0 } });
    await waitFor(() => expect(view.result.current.data).not.toBeNull());
    view.rerender({ active: false, refreshKey: 1 });
    expect(load).toHaveBeenCalledTimes(1);
    view.rerender({ active: true, refreshKey: 1 });
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
  });
});
