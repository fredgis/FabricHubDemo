import { StrictMode, type ReactNode } from 'react';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { OntologyGraph as Result } from '../../apps/cockpit/rayfin/functions/src/ontology-graph';

const invoke = vi.hoisted(() => vi.fn());
vi.mock('../../apps/cockpit/src/services/rayfinClient', () => ({
  getRayfinClient: () => ({ functions: { businessGraphSlice: { invoke } } }),
}));
import { OntologyGraph } from '../../apps/cockpit/src/components/OntologyGraph';
import { ReadCacheContext } from '../../apps/cockpit/src/hooks/ReadCacheContext';
import { createReadCache, type ReadCache } from '../../apps/cockpit/src/services/readCache';
const withCache = (cache: ReadCache) => ({ children }: { children: ReactNode }) =>
  <ReadCacheContext.Provider value={cache}>{children}</ReadCacheContext.Provider>;
const fixture = (): Result => ({
  state: 'ready', limit: 12, queried_at: '2026-10-10T12:30:00Z', generation: 2,
  source: { workspace_id: 'fixture', ontology_id: 'fixture', graph_model_id: 'fixture', gold_item_id: 'fixture' }, message: 'Fixture',
  nodes: [
    { key: 'customer:C1', type: 'customer', label: 'Fixture customer' },
    { key: 'rental:R2', type: 'rental', label: 'R2', created_at: '2026-10-10T12:01:00Z', status: 'active', amount_minor: 399, currency: 'EUR' },
    { key: 'offer:O2', type: 'offer', label: 'O2' },
    { key: 'content:F2', type: 'content', label: 'Fixture newest film' },
    { key: 'rental:R1', type: 'rental', label: 'R1', created_at: '2026-10-10T12:00:00Z', status: 'purchased' },
    { key: 'offer:O1', type: 'offer', label: 'O1' },
    { key: 'content:F1', type: 'content', label: 'Fixture earlier film' },
    { key: 'playback:P2', type: 'playback', label: 'P2', status: 'playing', position_seconds: 25 },
  ],
  edges: [
    { from: 'customer:C1', to: 'rental:R2', type: 'customer_order' },
    { from: 'rental:R2', to: 'offer:O2', type: 'order_offer' },
    { from: 'offer:O2', to: 'content:F2', type: 'offer_content' },
    { from: 'customer:C1', to: 'rental:R1', type: 'customer_order' },
    { from: 'rental:R1', to: 'offer:O1', type: 'order_offer' },
    { from: 'offer:O1', to: 'content:F1', type: 'offer_content' },
    { from: 'playback:P2', to: 'rental:R2', type: 'playback_order' },
    { from: 'playback:P2', to: 'content:F2', type: 'playback_content' },
  ],
  context: { playback_limit: 200, playback_truncated: false, distributor_limit: 200, distributors_truncated: false },
});
beforeEach(() => { invoke.mockReset(); invoke.mockResolvedValue(fixture()); });
afterEach(cleanup);
const ready = () => screen.findByRole('list', { name: 'Orders, newest first' });

it('supports explicit prefetch of twelve source paths and reuses the read when opened', async () => {
  const view = render(<OntologyGraph active={false} prefetch renderCanvas={false} />);
  await ready();
  expect(invoke).toHaveBeenCalledExactlyOnceWith({ journeyLimit: 12 });
  expect(view.container.querySelector('.ontology-canvas')).toBeNull();
  view.rerender(<OntologyGraph active prefetch renderCanvas={false} />);
  expect(invoke).toHaveBeenCalledOnce();
});
it('does not prefetch by default and does not poll or reload on tab revisits', async () => {
  const view = render(<OntologyGraph active={false} renderCanvas={false} />);
  expect(invoke).not.toHaveBeenCalled();
  view.rerender(<OntologyGraph active renderCanvas={false} />); await ready();
  view.rerender(<OntologyGraph active={false} refreshKey={1} renderCanvas={false} />);
  expect(invoke).toHaveBeenCalledOnce();
  view.rerender(<OntologyGraph active refreshKey={1} renderCanvas={false} />);
  await waitFor(() => expect(invoke).toHaveBeenCalledTimes(2));
  view.rerender(<OntologyGraph active={false} refreshKey={1} renderCanvas={false} />);
  view.rerender(<OntologyGraph active refreshKey={1} renderCanvas={false} />);
  expect(invoke).toHaveBeenCalledTimes(2);
});
it('lists newest orders first, focuses the newest and supports keyboard selection and show-all', async () => {
  const user = userEvent.setup(); render(<OntologyGraph renderCanvas={false} />);
  const buttons = within(await ready()).getAllByRole('button');
  expect(buttons[0]).toHaveTextContent('Order R2'); expect(buttons[0]).toHaveAttribute('aria-pressed', 'true');
  expect(buttons[1]).toHaveTextContent('Order R1');
  expect(screen.getByText('1 of 2 matching orders shown.')).toBeInTheDocument();
  const inspector = screen.getByRole('complementary', { name: 'Selected graph node' });
  expect(within(inspector).getByText('Recorded amount')).toBeInTheDocument();
  expect(within(inspector).getByText(/Session P2/)).toBeInTheDocument();
  buttons[1].focus(); await user.keyboard('{Enter}');
  expect(buttons[1]).toHaveAttribute('aria-pressed', 'true');
  expect(within(screen.getByRole('complementary', { name: 'Selected graph node' })).getByRole('heading', { name: 'R1' })).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Show all 2 orders' }));
  expect(screen.getByText('2 of 2 matching orders shown.')).toBeInTheDocument();
  expect(screen.queryByRole('complementary', { name: 'Selected graph node' })).toBeNull();
  expect(invoke).toHaveBeenCalledOnce();
});
it('searches only the loaded window and preserves whole matching paths without another call', async () => {
  const user = userEvent.setup(); render(<OntologyGraph renderCanvas={false} />); await ready();
  await user.type(screen.getByRole('searchbox'), 'earlier film');
  expect(within(await ready()).getAllByRole('button')).toHaveLength(1);
  expect(screen.getByText('1 of 1 matching orders shown.')).toBeInTheDocument();
  expect(screen.getByText('4 nodes / 3 relationships')).toBeInTheDocument();
  await user.clear(screen.getByRole('searchbox')); await user.type(screen.getByRole('searchbox'), 'missing');
  expect(screen.getByRole('heading', { name: 'No matching orders' })).toBeInTheDocument();
  expect(screen.getByText(/Search stays within the latest 12 loaded orders/)).toBeInTheDocument();
  expect(invoke).toHaveBeenCalledOnce();
});
it('uses already loaded rows for a smaller limit and fetches when expanding the window', async () => {
  const user = userEvent.setup(); render(<OntologyGraph renderCanvas={false} />); await ready();
  await user.selectOptions(screen.getByRole('combobox'), '6'); expect(invoke).toHaveBeenCalledOnce();
  invoke.mockResolvedValue({ ...fixture(), limit: 24 });
  await user.selectOptions(screen.getByRole('combobox'), '24');
  await waitFor(() => expect(invoke).toHaveBeenCalledTimes(2));
  expect(invoke).toHaveBeenLastCalledWith({ journeyLimit: 24 });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Refresh graph' })).toBeEnabled());
  await user.click(screen.getByRole('button', { name: 'Refresh graph' }));
  await waitFor(() => expect(invoke).toHaveBeenCalledTimes(3));
});
it('keeps the last successful result on failure and reports its own read state', async () => {
  const user = userEvent.setup(); const onRead = vi.fn(); render(<OntologyGraph renderCanvas={false} onRead={onRead} />); await ready();
  expect(onRead).toHaveBeenLastCalledWith({ loading: false, queriedAt: '2026-10-10T12:30:00Z' });
  invoke.mockRejectedValueOnce(new Error('Fixture query failure'));
  await user.click(screen.getByRole('button', { name: 'Refresh graph' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('The last successful graph remains visible');
  expect(within(await ready()).getAllByRole('button')).toHaveLength(2);
  expect(onRead).toHaveBeenCalledWith({ loading: true, queriedAt: '2026-10-10T12:30:00Z' });
  expect(onRead).toHaveBeenLastCalledWith({ loading: false, queriedAt: '2026-10-10T12:30:00Z' });
  expect(invoke).toHaveBeenCalledTimes(2);
});
it('explains missing distributors, context caps and the Gold-to-Graph publication boundary', async () => {
  const result = fixture(); result.context!.playback_truncated = true;
  invoke.mockResolvedValue(result);
  const user = userEvent.setup(); render(<OntologyGraph renderCanvas={false} />); await ready();
  expect(screen.getByText(/No distributor relationship is published/)).toBeInTheDocument();
  expect(screen.getByText(/Viewing sessions are capped at 200/)).toBeInTheDocument();
  await user.click(screen.getByText('Source and freshness'));
  expect(screen.getByText(/New transactions appear after Gold publication/)).toBeVisible();
  expect(screen.getByText(/Sessions have no timestamp/)).toBeVisible();
});
it.each([
  ['empty', 'No published order paths'], ['pending', 'Graph read pending'], ['binding-mismatch', 'Gold ontology binding pending'],
] as const)('renders the honest %s state', async (state, heading) => {
  invoke.mockResolvedValue({ ...fixture(), state, nodes: [], edges: [] });
  render(<OntologyGraph renderCanvas={false} />);
  expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument();
  expect(screen.queryByRole('list', { name: 'Orders, newest first' })).toBeNull();
});
it('announces an initial load without inventing an empty graph', () => {
  invoke.mockReturnValue(new Promise(() => {})); render(<OntologyGraph renderCanvas={false} />);
  expect(screen.getByRole('status')).toHaveTextContent('Reading the newest orders');
  expect(screen.getByRole('button', { name: 'Reading graph…' })).toBeDisabled();
});

it('restores graph data, search and limit after a full remount without another query', async () => {
  const user = userEvent.setup();
  const first = render(<OntologyGraph renderCanvas={false} />, { wrapper: withCache(createReadCache('graph-user')) });
  await ready();
  await user.selectOptions(screen.getByRole('combobox'), '6');
  await user.type(screen.getByRole('searchbox'), 'Fixture');
  first.unmount();
  render(<OntologyGraph renderCanvas={false} />, { wrapper: withCache(createReadCache('graph-user')) });
  expect(screen.getByRole('combobox')).toHaveValue('6');
  expect(screen.getByRole('searchbox')).toHaveValue('Fixture');
  expect(screen.getByRole('list', { name: 'Orders, newest first' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Refresh graph' })).toBeEnabled();
  expect(invoke).toHaveBeenCalledOnce();
  await user.click(screen.getByRole('button', { name: 'Refresh graph' }));
  await waitFor(() => expect(invoke).toHaveBeenCalledTimes(2));
});

it('waits until an invalidated hidden graph becomes active before reloading it', async () => {
  const cache = createReadCache('inactive-graph');
  const view = render(<OntologyGraph renderCanvas={false} />, { wrapper: withCache(cache) });
  await ready();
  view.rerender(<OntologyGraph active={false} renderCanvas={false} />);
  act(() => { cache.invalidate('read:'); });
  expect(invoke).toHaveBeenCalledOnce();
  view.rerender(<OntologyGraph active renderCanvas={false} />);
  await waitFor(() => expect(invoke).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Refresh graph' })).toBeEnabled());
});

it.each(['success', 'failure'])('ignores a late graph %s from before business invalidation', async outcome => {
  const cache = createReadCache('graph-race');
  let finishOld!: (value: Result) => void;
  let failOld!: (error: Error) => void;
  let finishNew!: (value: Result) => void;
  invoke.mockImplementationOnce(() => new Promise((resolve, reject) => { finishOld = resolve; failOld = reject; }))
    .mockImplementationOnce(() => new Promise(resolve => { finishNew = resolve; }));
  const onRead = vi.fn();
  render(<OntologyGraph renderCanvas={false} onRead={onRead} />, { wrapper: withCache(cache) });
  await act(async () => { cache.invalidate('read:'); });
  const latest = { ...fixture(), queried_at: '2026-10-11T12:00:00Z' };
  await act(async () => { finishNew(latest); });
  await act(async () => {
    if (outcome === 'success') finishOld(fixture());
    else failOld(new Error('Obsolete graph failure'));
  });
  expect(onRead).toHaveBeenLastCalledWith({ loading: false, queriedAt: latest.queried_at });
  expect(cache.get('read:graph:12')).toBe(latest);
  expect(screen.queryByRole('alert')).toBeNull();
  expect(invoke).toHaveBeenCalledTimes(2);
});

it('retries on activation after an obsolete request failed while the graph was hidden', async () => {
  const cache = createReadCache('graph-hidden-race');
  let failOld!: (error: Error) => void;
  invoke.mockImplementationOnce(() => new Promise((_resolve, reject) => { failOld = reject; }))
    .mockResolvedValueOnce(fixture());
  const view = render(<OntologyGraph renderCanvas={false} active />, { wrapper: withCache(cache) });
  view.rerender(<OntologyGraph renderCanvas={false} active={false} />);
  await act(async () => { cache.invalidate('read:'); });
  await act(async () => { failOld(new Error('Obsolete hidden graph error')); });
  expect(screen.queryByRole('alert')).toBeNull();
  view.rerender(<OntologyGraph renderCanvas={false} active />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Refresh graph' })).toBeEnabled());
  expect(invoke).toHaveBeenCalledTimes(2);
  expect(cache.get('read:graph:12')).toEqual(fixture());
});

it('finishes its deduplicated initial read under StrictMode', async () => {
  const onRead = vi.fn();
  render(<StrictMode><OntologyGraph renderCanvas={false} onRead={onRead} /></StrictMode>);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Refresh graph' })).toBeEnabled());
  expect(onRead).toHaveBeenLastCalledWith({ loading: false, queriedAt: fixture().queried_at });
  expect(invoke).toHaveBeenCalledOnce();
});
