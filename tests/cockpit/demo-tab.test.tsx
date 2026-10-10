import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { GoldPages } from '../../apps/cockpit/rayfin/functions/src/gold-pages';

const reads = vi.hoisted(() => ({ gold: vi.fn(), reloads: vi.fn(), graph: vi.fn() }));
vi.mock('../../apps/cockpit/src/hooks/AuthContext', () => ({
  useAuth: () => ({ user: { name: 'Demo viewer' }, signOut: vi.fn() }),
}));
vi.mock('../../apps/cockpit/src/services/rayfinClient', () => ({
  getRayfinClient: () => ({ functions: {
    capabilities: { invoke: async () => ({ can_operate: false, reason: 'Viewer test actor.' }) },
    businessGraphSlice: { invoke: reads.graph },
    health: { invoke: async () => ({ database: 'Test store', functions: 'Test functions', outbox_pending: 0, broker: 'Test broker' }) },
  } }),
}));
vi.mock('../../apps/cockpit/src/services/source-reloads', async importOriginal => ({
  ...await importOriginal<typeof import('../../apps/cockpit/src/services/source-reloads')>(),
  readSourceReloads: reads.reloads,
}));
vi.mock('../../apps/cockpit/src/services/business', async importOriginal => {
  const original = await importOriginal<typeof import('../../apps/cockpit/src/services/business')>();
  return { ...original, loadSnapshot: async () => ({
    content: [], customers: [], offers: [], rentals: [], playback: [], outbox: [], commands: [],
    campaigns: [], members: [], links: [],
  }) };
});
vi.mock('../../apps/cockpit/src/services/goldViews', () => ({ loadGoldViews: reads.gold }));
import { HomePage } from '../../apps/cockpit/src/pages/HomePage';

beforeEach(() => {
  vi.resetAllMocks();
  const pages: GoldPages = {
    dashboard: {
      source: { name: 'MSFlixGold', workspace_id: 'workspace', item_id: 'gold', views: [] },
      state: 'empty', freshness: { queried_at: '2026-10-10T12:00:00Z', published_at: null,
        publication_run_id: null, order_lines: '0' },
      commercial: [], playback: [], campaigns: [], dimensions: { customers: '0', content: '0' },
    },
    catalog: [], customers: [], offers: [], orders: [], sessions: [], campaigns: [],
    window: { orders: 6, sessions: 6, references: 10000 },
  };
  reads.gold.mockResolvedValue({ pages, snapshot: {
    content: [], customers: [], offers: [], rentals: [], playback: [], outbox: [], commands: [],
    campaigns: [], members: [], links: [],
  } });
  reads.reloads.mockResolvedValue([]);
  reads.graph.mockResolvedValue({ state: 'empty', limit: 6, nodes: [], edges: [], message: 'No test graph instances.' });
});
afterEach(cleanup);

it('opens an actual Demo tab in the existing cockpit and retains it across navigation', async () => {
  render(<HomePage />);
  const tab = screen.getByRole('button', { name: 'Demo' });
  fireEvent.click(tab);
  expect(tab).toHaveAttribute('aria-current', 'page');
  expect(screen.getByRole('heading', { name: 'Demo', level: 1 })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Launch a bounded demo' })).toBeInTheDocument();
  expect(await screen.findByRole('button', { name: 'Start demo' })).toBeDisabled();
  await screen.findByText('Oracle: no persisted reload request');
  fireEvent.change(screen.getByRole('spinbutton', { name: 'Journey count' }), { target: { value: '3' } });
  fireEvent.click(screen.getByRole('button', { name: 'Rentals & Purchases' }));
  expect(screen.queryByRole('heading', { name: 'Launch a bounded demo' })).not.toBeInTheDocument();
  fireEvent.click(tab);
  expect(screen.getByRole('spinbutton', { name: 'Journey count' })).toHaveValue(3);
  await act(async () => {});
  expect(reads.reloads).toHaveBeenCalledTimes(2);
});

it('keeps hidden graph and reload reads idle, then reads the graph on entry and explicit refresh', async () => {
  render(<HomePage />);
  await screen.findByText('Your catalog starts here');
  expect(reads.graph).not.toHaveBeenCalled();
  for (const name of ['Catalog', 'Rentals & Purchases', 'Operations']) {
    await act(async () => { fireEvent.click(screen.getByRole('button', { name })); });
    expect(reads.graph).not.toHaveBeenCalled();
    expect(reads.reloads).not.toHaveBeenCalled();
  }
  fireEvent.click(screen.getByRole('button', { name: 'Business Graph' }));
  await screen.findByText('No test graph instances.');
  expect(reads.graph).toHaveBeenCalledExactlyOnceWith({ journeyLimit: 6 });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Overview' })); });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Business Graph' })); });
  expect(reads.graph).toHaveBeenCalledOnce();
  fireEvent.click(within(screen.getByRole('banner')).getByRole('button', { name: 'Refresh graph' }));
  await waitFor(() => expect(reads.graph).toHaveBeenCalledTimes(2));
  expect(reads.reloads).not.toHaveBeenCalled();
});
