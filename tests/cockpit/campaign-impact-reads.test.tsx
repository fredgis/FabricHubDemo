import { StrictMode, type ReactNode } from 'react';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { campaignImpactFixture } from './campaign-impact-fixture';

const load = vi.hoisted(() => vi.fn());
vi.mock('../../apps/cockpit/src/services/campaignImpact', () => ({ loadCampaignImpact: load }));
import { useCampaignImpact } from '../../apps/cockpit/src/hooks/useCampaignImpact';

afterEach(cleanup);
beforeEach(() => { load.mockReset(); load.mockResolvedValue(campaignImpactFixture()); });

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

it('reads only while active, caches revisits and defers hidden refreshes', async () => {
  const view = renderHook(({ active, refreshKey }) => useCampaignImpact(active, refreshKey), { initialProps: { active: false, refreshKey: 0 } });
  expect(load).not.toHaveBeenCalled();
  view.rerender({ active: true, refreshKey: 0 });
  await waitFor(() => expect(view.result.current.data?.summary.contacted_customers).toBe(600));
  view.rerender({ active: false, refreshKey: 0 });
  view.rerender({ active: true, refreshKey: 0 });
  expect(load).toHaveBeenCalledTimes(1);
  view.rerender({ active: false, refreshKey: 1 });
  expect(load).toHaveBeenCalledTimes(1);
  view.rerender({ active: true, refreshKey: 1 });
  await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
  expect(load).toHaveBeenLastCalledWith(campaignImpactFixture().filters);
});

it('coalesces StrictMode and simultaneous identical requests', async () => {
  const initial = deferred<ReturnType<typeof campaignImpactFixture>>();
  load.mockReturnValue(initial.promise);
  const view = renderHook(() => useCampaignImpact(true, 0), { wrapper: ({ children }: { children: ReactNode }) => <StrictMode>{children}</StrictMode> });
  act(() => { void view.result.current.refresh(); void view.result.current.apply({}); });
  expect(load).toHaveBeenCalledTimes(1);
  await act(async () => { initial.resolve(campaignImpactFixture()); await initial.promise; });
  expect(view.result.current.loading).toBe(false);
  expect(view.result.current.data?.summary.engaged_per_100_minor).toBe('0');
});

it('ignores a late response from an older currency selection', async () => {
  const older = deferred<ReturnType<typeof campaignImpactFixture>>();
  const newer = deferred<ReturnType<typeof campaignImpactFixture>>();
  load.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
  const view = renderHook(() => useCampaignImpact(true, 0));
  act(() => { void view.result.current.apply({ currency: 'JPY' }); });
  const filtered = campaignImpactFixture({ filters: { ...campaignImpactFixture().filters, currency: 'JPY' } });
  await act(async () => { newer.resolve(filtered); await newer.promise; });
  await act(async () => { older.resolve(campaignImpactFixture()); await older.promise; });
  expect(view.result.current.data?.filters.currency).toBe('JPY');
  expect(view.result.current.loading).toBe(false);
  expect(view.result.current.error).toBe('');
});

it('preserves previous data after failure and retries the failed selection, not the old one', async () => {
  const view = renderHook(() => useCampaignImpact(true, 0));
  await waitFor(() => expect(view.result.current.data).not.toBeNull());
  const previous = view.result.current.data;
  load.mockRejectedValueOnce(new Error('Temporary Gold failure'));
  await act(async () => { await view.result.current.apply({ territory: 'US', currency: 'USD' }); });
  expect(view.result.current.data).toBe(previous);
  expect(view.result.current.error).toContain('Temporary Gold failure');
  await act(async () => { await view.result.current.refresh(); });
  expect(load).toHaveBeenLastCalledWith({ territory: 'US', currency: 'USD' });
  expect(view.result.current.error).toBe('');
});
