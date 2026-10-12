import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { campaignImpactFixture } from './campaign-impact-fixture';
import { insightsFixture } from './insights-fixture';

const { readers, auth } = vi.hoisted(() => ({
  readers: { gold: vi.fn(), operational: vi.fn(), insights: vi.fn(), campaign: vi.fn() },
  auth: { isAuthenticated: true, loading: false },
}));
vi.mock('../../apps/cockpit/src/services/goldViews', () => ({ loadGoldViews: readers.gold }));
vi.mock('../../apps/cockpit/src/services/business', async importOriginal => ({
  ...await importOriginal<typeof import('../../apps/cockpit/src/services/business')>(),
  loadSnapshot: readers.operational,
}));
vi.mock('../../apps/cockpit/src/services/insights', () => ({ loadGoldInsights: readers.insights }));
vi.mock('../../apps/cockpit/src/services/campaignImpact', () => ({ loadCampaignImpact: readers.campaign }));
vi.mock('../../apps/cockpit/src/hooks/AuthContext', () => ({ useAuth: () => ({
  ...auth, user: { id: 'test-viewer', name: 'Test viewer' }, signOut: vi.fn(), signIn: vi.fn(),
}) }));
vi.mock('../../apps/cockpit/src/services/rayfinClient', () => ({ getRayfinClient: () => ({ functions: {
  capabilities: { invoke: async () => ({ can_operate: false, reason: 'Read-only viewer' }) },
} }) }));
import App from '../../apps/cockpit/src/App';
import { HomePage } from '../../apps/cockpit/src/pages/HomePage';

const navButton = (name: string) => within(screen.getByRole('navigation', { name: 'Main navigation' }))
  .getByRole('button', { name, exact: true });
const ready = async () => {
  const frame = await screen.findByTitle<HTMLIFrameElement>('MSFlix data flow explorer');
  expect(frame).toBeInTheDocument();
  await act(async () => { fireEvent.load(frame); });
  return frame;
};

beforeEach(() => {
  vi.clearAllMocks();
  const documents = new WeakMap<HTMLIFrameElement, Document>();
  // jsdom loads about:blank before findByTitle resolves and never initializes srcDoc.
  vi.spyOn(HTMLIFrameElement.prototype, 'contentDocument', 'get').mockImplementation(function (this: HTMLIFrameElement) {
    let embedded = documents.get(this);
    if (!embedded) {
      embedded = document.implementation.createHTMLDocument('Test Data Flow');
      embedded.documentElement.dataset.explorerReady = 'true';
      documents.set(this, embedded);
    }
    return embedded;
  });
  auth.isAuthenticated = true; auth.loading = false;
  readers.gold.mockRejectedValue(new Error('Gold is unavailable in this test'));
  readers.operational.mockRejectedValue(new Error('Operational SQL is unavailable in this test'));
  readers.insights.mockResolvedValue(insightsFixture());
  readers.campaign.mockResolvedValue(campaignImpactFixture());
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.history.replaceState({}, '', '/'); });

it('loads only when first visited and preserves the frame while refreshing it independently', async () => {
  render(<HomePage />);
  await screen.findByText('Read-only viewer');
  expect(screen.queryByTitle('MSFlix data flow explorer')).not.toBeInTheDocument();
  fireEvent.click(navButton('Data Flow'));
  const frame = await ready();
  frame.contentDocument!.documentElement.dataset.theme = 'light';
  expect(navButton('Data Flow')).toHaveAttribute('aria-current', 'page');
  expect(screen.queryByText(/Gold is unavailable/)).not.toBeInTheDocument();
  expect(screen.queryByText('No data read yet')).not.toBeInTheDocument();
  expect(screen.queryByText('Read-only viewer')).not.toBeInTheDocument();
  fireEvent.click(navButton('Catalog'));
  expect(frame).not.toBeVisible();
  await waitFor(() => expect(readers.gold).toHaveBeenCalledWith('catalog'));
  fireEvent.click(navButton('Data Flow'));
  expect(screen.getByTitle('MSFlix data flow explorer')).toBe(frame);
  expect(frame.contentDocument!.documentElement.dataset.theme).toBe('light');
  const previousReads = readers.gold.mock.calls.length;
  fireEvent.click(screen.getByRole('button', { name: 'Refresh data flow' }));
  const refreshed = await ready();
  expect(refreshed).not.toBe(frame);
  expect(readers.gold).toHaveBeenCalledTimes(previousReads);
  expect(readers.operational).not.toHaveBeenCalled();
});

it('opens the authenticated route without business reads and preserves other routed sections', async () => {
  window.history.replaceState({}, '', '/dataflow');
  render(<App />);
  const frame = await ready();
  expect(readers.gold).not.toHaveBeenCalled();
  expect(readers.operational).not.toHaveBeenCalled();
  fireEvent.click(navButton('MSFlix Insights'));
  await screen.findByRole('form', { name: 'Filter Gold analysis' });
  fireEvent.change(screen.getByLabelText('Genre'), { target: { value: 'Animation' } });
  fireEvent.click(navButton('Campaign Impact'));
  const campaignForm = await screen.findByRole('form', { name: 'Filter campaign impact' });
  fireEvent.change(within(campaignForm).getByLabelText('Currency'), { target: { value: 'JPY' } });
  fireEvent.click(navButton('Data Flow'));
  expect(window.location.pathname).toBe('/dataflow');
  expect(screen.getByTitle('MSFlix data flow explorer')).toBe(frame);
  fireEvent.click(screen.getByRole('button', { name: 'Refresh data flow' }));
  await ready();
  window.history.back();
  await waitFor(() => expect(window.location.pathname).toBe('/campaign-impact'));
  expect(within(await screen.findByRole('form', { name: 'Filter campaign impact' }))
    .getByLabelText('Currency')).toHaveValue('JPY');
  window.history.back();
  await waitFor(() => expect(window.location.pathname).toBe('/'));
  expect(screen.getByLabelText('Genre')).toHaveValue('Animation');
  window.history.forward();
  await waitFor(() => expect(window.location.pathname).toBe('/campaign-impact'));
  window.history.forward();
  await waitFor(() => expect(window.location.pathname).toBe('/dataflow'));
  expect(screen.getByTitle('MSFlix data flow explorer')).toBeVisible();
  expect(readers.insights).toHaveBeenCalledOnce();
  expect(readers.campaign).toHaveBeenCalledOnce();
  expect(readers.gold).not.toHaveBeenCalled();
  expect(readers.operational).not.toHaveBeenCalled();
});

it('expands and restores the shell without reloading the embedded document', async () => {
  render(<HomePage route="/dataflow" />);
  const frame = await ready();
  fireEvent.click(screen.getByRole('button', { name: 'Expand view' }));
  expect(screen.queryByRole('navigation', { name: 'Main navigation' })).not.toBeInTheDocument();
  const restore = screen.getByRole('button', { name: 'Restore navigation' });
  expect(restore).toHaveAttribute('aria-pressed', 'true');
  expect(restore).toHaveAttribute('aria-controls', 'dataflow-panel');
  expect(frame.closest('.app-shell')).toHaveClass('app-shell--dataflow-expanded');
  fireEvent.click(restore);
  expect(navButton('Data Flow')).toBeVisible();
  expect(screen.getByTitle('MSFlix data flow explorer')).toBe(frame);
});

it('retries a failed document without retrying Gold or operational SQL', async () => {
  render(<HomePage route="/dataflow" />);
  const frame = await screen.findByTitle<HTMLIFrameElement>('MSFlix data flow explorer');
  delete frame.contentDocument!.documentElement.dataset.explorerReady;
  fireEvent.load(frame);
  fireEvent.click(screen.getByRole('button', { name: 'Retry data flow' }));
  expect(await ready()).not.toBe(frame);
  expect(readers.gold).not.toHaveBeenCalled();
  expect(readers.operational).not.toHaveBeenCalled();
});

it('does not block document refresh on an unrelated pending business read', async () => {
  readers.gold.mockImplementationOnce(() => new Promise(() => {}));
  render(<HomePage />);
  fireEvent.click(navButton('Data Flow'));
  const frame = await ready();
  const refresh = screen.getByRole('button', { name: 'Refresh data flow' });
  expect(refresh).toBeEnabled();
  fireEvent.click(refresh);
  expect(await ready()).not.toBe(frame);
  expect(readers.gold).toHaveBeenCalledOnce();
});

it('does not expose the page before authentication has finished', () => {
  auth.loading = true;
  window.history.replaceState({}, '', '/dataflow');
  render(<App />);
  expect(screen.getByText('Verifying Fabric identity…')).toBeInTheDocument();
  expect(screen.queryByTitle('MSFlix data flow explorer')).not.toBeInTheDocument();
  expect(readers.gold).not.toHaveBeenCalled();
});

it('keeps /dataflow behind the existing sign-in guard', async () => {
  auth.isAuthenticated = false;
  window.history.replaceState({}, '', '/dataflow');
  render(<App />);
  await screen.findByRole('button', { name: 'Sign in with Microsoft' });
  expect(window.location.pathname).toBe('/auth');
  expect(screen.queryByTitle('MSFlix data flow explorer')).not.toBeInTheDocument();
  expect(readers.gold).not.toHaveBeenCalled();
  expect(readers.operational).not.toHaveBeenCalled();
});
