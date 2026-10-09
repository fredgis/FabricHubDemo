import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { insightsFixture } from './insights-fixture';

const load = vi.hoisted(() => vi.fn());
vi.mock('../../apps/cockpit/src/services/insights', () => ({ loadGoldInsights: load }));
vi.mock('../../apps/cockpit/src/hooks/AuthContext', () => ({ useAuth: () => ({ user: { id: 'test-viewer', name: 'Test viewer' }, signOut: vi.fn() }) }));
vi.mock('../../apps/cockpit/src/services/rayfinClient', () => ({
  getRayfinClient: () => ({ functions: { capabilities: { invoke: async () => ({ can_operate: false, reason: 'Read-only viewer' }) } } }),
}));
vi.mock('../../apps/cockpit/src/services/goldViews', () => ({ loadGoldViews: async () => { throw new Error('Baseline unavailable in this test'); } }));
import { HomePage } from '../../apps/cockpit/src/pages/HomePage';

afterEach(cleanup);
beforeEach(() => { load.mockReset(); load.mockResolvedValue(insightsFixture()); });

it('places Insights immediately after Business Graph and preserves its draft across navigation', async () => {
  render(<HomePage />);
  await screen.findByText('Read-only viewer');
  const nav = screen.getByRole('navigation', { name: 'Main navigation' });
  const labels = within(nav).getAllByRole('button').map(button => button.textContent);
  expect(labels.indexOf('MSFlix Insights')).toBe(labels.indexOf('Business Graph') + 1);
  expect(load).not.toHaveBeenCalled();
  fireEvent.click(within(nav).getByRole('button', { name: 'MSFlix Insights' }));
  await screen.findByRole('form', { name: 'Filter Gold analysis' });
  fireEvent.change(screen.getByLabelText('Genre'), { target: { value: 'Animation' } });
  fireEvent.click(within(nav).getByRole('button', { name: 'Catalog' }));
  expect(screen.queryByRole('form', { name: 'Filter Gold analysis' })).not.toBeInTheDocument();
  fireEvent.click(within(nav).getByRole('button', { name: 'MSFlix Insights' }));
  expect(screen.getByLabelText('Genre')).toHaveValue('Animation');
  expect(load).toHaveBeenCalledTimes(1);
  expect(screen.queryByText(/Baseline unavailable/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Refresh insights' }));
  await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
  expect(load).toHaveBeenLastCalledWith(insightsFixture().filters);
});
