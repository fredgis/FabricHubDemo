import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { GoldCatalogDashboard, GoldDashboard } from '../../apps/cockpit/rayfin/functions/src/gold-dashboard';

const invoke = vi.hoisted(() => vi.fn());
vi.mock('../../apps/cockpit/src/services/rayfinClient', () => ({
  getRayfinClient: () => ({ functions: { businessDashboard: { invoke } } }),
}));
import { GoldBusinessDashboard } from '../../apps/cockpit/src/components/GoldBusinessDashboard';
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const full: GoldDashboard = {
  source: { name: 'MSFlixGold', item_id: 'fixture-gold', workspace_id: 'fixture-workspace', views: [] },
  state: 'ready', freshness: { queried_at: '2026-10-10T12:00:00Z', published_at: '2026-10-10T11:00:00Z',
    publication_run_id: 'fixture-publication', order_lines: '0' },
  commercial: [], playback: [], campaigns: [], dimensions: { customers: '0', content: '0' },
};
const catalog: GoldCatalogDashboard = {
  ...full, scope: 'catalog', commercial: null, playback: null, campaigns: null, dimensions: null,
};

it('does not treat omitted Catalog aggregates as zero metrics or fetch replacements', () => {
  render(<GoldBusinessDashboard dashboard={catalog} />);
  expect(screen.queryByLabelText('Curated Gold business metrics')).not.toBeInTheDocument();
  expect(screen.queryByText('No curated business activity')).not.toBeInTheDocument();
  expect(invoke).not.toHaveBeenCalled();
});

it('drops stale metrics immediately when the provided scope changes to Catalog', () => {
  const view = render(<GoldBusinessDashboard dashboard={full} />);
  expect(screen.getByText('Recorded sales')).toBeInTheDocument();
  view.rerender(<GoldBusinessDashboard dashboard={catalog} />);
  expect(screen.queryByText('Recorded sales')).not.toBeInTheDocument();
  view.rerender(<GoldBusinessDashboard dashboard={full} />);
  expect(screen.getByText('Recorded sales')).toBeInTheDocument();
  expect(invoke).not.toHaveBeenCalled();
});
