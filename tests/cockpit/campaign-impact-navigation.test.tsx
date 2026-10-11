import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { campaignImpactFixture } from './campaign-impact-fixture';
import { insightsFixture } from './insights-fixture';

const { load, insights, auth } = vi.hoisted(() => ({ load: vi.fn(), insights: vi.fn(), auth: { isAuthenticated: true } }));
vi.mock('../../apps/cockpit/src/services/campaignImpact', () => ({ loadCampaignImpact: load }));
vi.mock('../../apps/cockpit/src/services/insights', () => ({ loadGoldInsights: insights }));
vi.mock('../../apps/cockpit/src/hooks/AuthContext', () => ({ useAuth: () => ({ ...auth, loading: false, user: { id: 'test-viewer', name: 'Test viewer' }, signOut: vi.fn(), signIn: vi.fn() }) }));
vi.mock('../../apps/cockpit/src/services/rayfinClient', () => ({ getRayfinClient: () => ({ functions: { capabilities: { invoke: async () => ({ can_operate: false, reason: 'Read-only viewer' }) } } }) }));
vi.mock('../../apps/cockpit/src/services/goldViews', () => ({ loadGoldViews: async () => { throw new Error('Baseline unavailable in this test'); } }));
import App from '../../apps/cockpit/src/App';
import { HomePage } from '../../apps/cockpit/src/pages/HomePage';

afterEach(() => { cleanup(); window.history.replaceState({}, '', '/'); });
beforeEach(() => {
  auth.isAuthenticated = true;
  load.mockReset(); load.mockResolvedValue(campaignImpactFixture());
  insights.mockReset(); insights.mockResolvedValue(insightsFixture());
});

it('places Campaign Impact immediately after Insights and scopes refreshes in the standalone shell', async () => {
  render(<HomePage />);
  await screen.findByText('Read-only viewer');
  const nav = screen.getByRole('navigation', { name: 'Main navigation' });
  const labels = within(nav).getAllByRole('button').map(button => button.textContent);
  expect(labels.indexOf('Campaign Impact')).toBe(labels.indexOf('MSFlix Insights') + 1);
  expect(load).not.toHaveBeenCalled();
  fireEvent.click(within(nav).getByRole('button', { name: 'Campaign Impact' }));
  await screen.findByRole('form', { name: 'Filter campaign impact' });
  fireEvent.change(screen.getByLabelText('Currency'), { target: { value: 'JPY' } });
  fireEvent.click(within(nav).getByRole('button', { name: 'Catalog' }));
  fireEvent.click(within(nav).getByRole('button', { name: 'Campaign Impact' }));
  expect(screen.getByLabelText('Currency')).toHaveValue('JPY');
  expect(load).toHaveBeenCalledTimes(1);
  expect(screen.queryByText(/Baseline unavailable/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Refresh campaign impact' }));
  await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
  expect(load).toHaveBeenLastCalledWith(campaignImpactFixture().filters);
  expect(insights).not.toHaveBeenCalled();
});

it('opens the real route directly and preserves the existing Insights section when navigating back', async () => {
  window.history.replaceState({}, '', '/campaign-impact');
  render(<App />);
  await screen.findByRole('form', { name: 'Filter campaign impact' });
  expect(screen.getByRole('heading', { level: 1, name: 'Campaign Impact' })).toBeInTheDocument();
  const nav = screen.getByRole('navigation', { name: 'Main navigation' });
  fireEvent.click(within(nav).getByRole('button', { name: 'MSFlix Insights' }));
  await screen.findByRole('form', { name: 'Filter Gold analysis' });
  expect(window.location.pathname).toBe('/');
  fireEvent.change(screen.getByLabelText('Genre'), { target: { value: 'Animation' } });
  fireEvent.click(within(nav).getByRole('button', { name: 'Campaign Impact' }));
  expect(window.location.pathname).toBe('/campaign-impact');
  expect(screen.getByRole('form', { name: 'Filter campaign impact' })).toBeInTheDocument();
  window.history.back();
  await waitFor(() => expect(window.location.pathname).toBe('/'));
  expect(await screen.findByRole('form', { name: 'Filter Gold analysis' })).toBeInTheDocument();
  expect(screen.getByLabelText('Genre')).toHaveValue('Animation');
  expect(load).toHaveBeenCalledTimes(1);
  expect(insights).toHaveBeenCalledTimes(1);
});

it('keeps the new route behind the existing authentication guard', async () => {
  auth.isAuthenticated = false;
  window.history.replaceState({}, '', '/campaign-impact');
  render(<App />);
  await screen.findByRole('button', { name: 'Sign in with Microsoft' });
  expect(window.location.pathname).toBe('/auth');
  expect(load).not.toHaveBeenCalled();
});
