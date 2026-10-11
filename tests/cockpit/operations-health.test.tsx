import { StrictMode, type ReactNode } from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { AuthUser } from '../../apps/cockpit/src/services/IAuthService';
import type { Snapshot } from '../../apps/cockpit/src/services/business';
import type { GoldPages } from '../../apps/cockpit/rayfin/functions/src/gold-pages';

const sdk = vi.hoisted(() => ({
  health: vi.fn(), capabilities: vi.fn(), requestControl: vi.fn(),
  auth: { user: { id: 'viewer-1', name: 'Test viewer', email: 'viewer@example.test' } as AuthUser | null },
}));
vi.mock('../../apps/cockpit/src/hooks/AuthContext', () => ({
  useAuth: () => ({ user: sdk.auth.user, signOut: vi.fn() }),
}));
vi.mock('../../apps/cockpit/src/services/rayfinClient', () => ({
  getRayfinClient: () => ({ functions: {
    health: { invoke: sdk.health }, capabilities: { invoke: sdk.capabilities },
    requestControl: { invoke: sdk.requestControl },
  } }),
}));
vi.mock('../../apps/cockpit/src/services/business', async importOriginal => ({
  ...await importOriginal<typeof import('../../apps/cockpit/src/services/business')>(),
  loadSnapshot: async () => snapshot,
}));
vi.mock('../../apps/cockpit/src/services/goldViews', () => ({
  loadGoldViews: async () => ({ pages, snapshot }),
}));
import { HomePage } from '../../apps/cockpit/src/pages/HomePage';
import { ReadCacheContext } from '../../apps/cockpit/src/hooks/ReadCacheContext';
import { createReadCache, type ReadCache } from '../../apps/cockpit/src/services/readCache';
const withCache = (cache: ReadCache) => ({ children }: { children: ReactNode }) =>
  <ReadCacheContext.Provider value={cache}>{children}</ReadCacheContext.Provider>;

const snapshot: Snapshot = {
  content: [], customers: [], offers: [], rentals: [], playback: [], outbox: [],
  commands: [], campaigns: [], members: [], links: [],
};
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
const health = { database: 'Connected test database', functions: 'Native test function', outbox_pending: 3, broker: 'Test delivery status' };
let now: number;

beforeEach(() => {
  vi.resetAllMocks();
  now = Date.parse('2026-10-10T12:00:00Z');
  vi.spyOn(Date, 'now').mockImplementation(() => now);
  sdk.auth.user = { id: 'viewer-1', name: 'Test viewer', email: 'viewer@example.test' };
  sdk.health.mockResolvedValue(health);
  sdk.capabilities.mockResolvedValue({ can_operate: false, reason: 'Read-only test viewer.' });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

async function navigate(name: string) {
  await act(async () => { fireEvent.click(screen.getByRole('button', { name })); });
}

function lastChecked() {
  return screen.getByText(/Last checked/).querySelector('time');
}

function deferredHealth() {
  let resolve!: (value: typeof health) => void;
  const promise = new Promise<typeof health>(done => { resolve = done; });
  return { promise, resolve };
}

it('reuses a successful health check and its timestamp when Operations remounts within 30 seconds', async () => {
  render(<HomePage />);
  await navigate('Operations');
  expect(screen.getByText('Connected test database')).toBeInTheDocument();
  expect(lastChecked()).toHaveAttribute('datetime', '2026-10-10T12:00:00.000Z');
  expect(lastChecked()).toHaveTextContent('Oct 10, 2026, 12:00:00 PM UTC');
  await navigate('Overview');
  now += 29_999;
  await navigate('Operations');
  expect(screen.getByText('Connected test database')).toBeInTheDocument();
  expect(lastChecked()).toHaveAttribute('datetime', '2026-10-10T12:00:00.000Z');
  expect(sdk.health).toHaveBeenCalledOnce();
});

it('keeps the health read after more than five minutes away until Check health is used', async () => {
  const view = render(<HomePage />);
  await navigate('Operations');
  now += 6 * 60_000;
  await act(async () => { view.rerender(<HomePage />); });
  expect(sdk.health).toHaveBeenCalledOnce();
  await navigate('Overview');
  await navigate('Operations');
  expect(sdk.health).toHaveBeenCalledOnce();
  expect(lastChecked()).toHaveAttribute('datetime', '2026-10-10T12:00:00.000Z');
  await navigate('Check health');
  expect(sdk.health).toHaveBeenCalledTimes(2);
  expect(lastChecked()).toHaveAttribute('datetime', '2026-10-10T12:06:00.000Z');
});

it('uses Check health as a keyboard-accessible force check without enabling operational commands', async () => {
  render(<HomePage />);
  await navigate('Operations');
  now += 10_000;
  const response = deferredHealth();
  sdk.health.mockReturnValueOnce(response.promise);
  const button = screen.getByRole('button', { name: 'Check health' });
  button.focus();
  await userEvent.setup().keyboard('{Enter}');
  expect(sdk.health).toHaveBeenCalledTimes(2);
  expect(screen.getByRole('button', { name: 'Checking…' })).toBeDisabled();
  expect(screen.getByRole('status')).toHaveTextContent('Invoking native health function');
  expect(screen.queryByText(/Last checked/)).not.toBeInTheDocument();
  await act(async () => { response.resolve({ ...health, outbox_pending: 0 }); });
  expect(lastChecked()).toHaveAttribute('datetime', '2026-10-10T12:00:10.000Z');
  expect(lastChecked()).toHaveTextContent('Oct 10, 2026, 12:00:10 PM UTC');
  expect(screen.getByRole('button', { name: 'Check health' })).toBeEnabled();
  for (const name of ['Request simulate', 'Request start', 'Request stop', 'Request refresh', 'Expire due rentals'])
    expect(screen.getByRole('button', { name })).toBeDisabled();
  expect(sdk.requestControl).not.toHaveBeenCalled();
  expect(sdk.capabilities).toHaveBeenCalledOnce();
});

it.each(['initial', 'forced'] as const)('shows a failed %s check, retries on remount and never restores stale health', async kind => {
  render(<HomePage />);
  if (kind === 'forced') await navigate('Operations');
  sdk.health.mockRejectedValue(new Error('Native health unavailable.'));
  await navigate(kind === 'initial' ? 'Operations' : 'Check health');
  expect(screen.getByRole('alert')).toHaveTextContent('Native health unavailable.');
  expect(screen.queryByText('Connected test database')).not.toBeInTheDocument();
  expect(screen.queryByText(/Last checked/)).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Check health' })).toBeEnabled();
  await navigate('Overview');
  await navigate('Operations');
  expect(screen.getByRole('alert')).toHaveTextContent('Native health unavailable.');
  expect(sdk.health).toHaveBeenCalledTimes(kind === 'initial' ? 2 : 3);
  sdk.health.mockResolvedValue(health);
  await navigate('Check health');
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(screen.getByText('Connected test database')).toBeInTheDocument();
  expect(lastChecked()).toBeInTheDocument();
});

it('deduplicates StrictMode checks and Operations remounts while the native read is pending', async () => {
  const response = deferredHealth();
  sdk.health.mockReturnValueOnce(response.promise);
  render(<StrictMode><HomePage /></StrictMode>);
  await navigate('Operations');
  expect(screen.getByRole('button', { name: 'Checking…' })).toBeDisabled();
  await navigate('Overview');
  await navigate('Operations');
  expect(sdk.health).toHaveBeenCalledOnce();
  await act(async () => { response.resolve(health); });
  expect(screen.getByText('Connected test database')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Check health' })).toBeEnabled();
});

it.each(['completed', 'pending'] as const)('isolates %s health reads when the authenticated identity changes', async state => {
  const response = deferredHealth();
  if (state === 'pending') sdk.health.mockReturnValueOnce(response.promise);
  const view = render(<HomePage />);
  await navigate('Operations');
  sdk.health.mockResolvedValueOnce({ ...health, database: 'New identity test database' });
  sdk.auth.user = { id: 'viewer-2', name: 'Second viewer', email: 'second@example.test' };
  await act(async () => { view.rerender(<HomePage />); });
  expect(screen.getByText('New identity test database')).toBeInTheDocument();
  expect(screen.queryByText('Connected test database')).not.toBeInTheDocument();
  if (state === 'pending') await act(async () => { response.resolve(health); });
  await navigate('Overview');
  await navigate('Operations');
  expect(screen.getByText('New identity test database')).toBeInTheDocument();
  expect(screen.queryByText('Connected test database')).not.toBeInTheDocument();
  expect(sdk.health).toHaveBeenCalledTimes(2);
  sdk.auth.user = { id: 'viewer-1', name: 'Test viewer', email: 'viewer@example.test' };
  await act(async () => { view.rerender(<HomePage />); });
  expect(sdk.health).toHaveBeenCalledTimes(3);
});

it('starts a new cache when the auth guard remounts the cockpit, even for the same identity', async () => {
  const view = render(<HomePage />);
  await navigate('Operations');
  view.unmount();
  now += 1_000;
  render(<HomePage />);
  await navigate('Operations');
  expect(sdk.health).toHaveBeenCalledTimes(2);
  expect(lastChecked()).toHaveAttribute('datetime', '2026-10-10T12:00:01.000Z');
});

it('does not hide permission errors or enable commands after a successful cached health read', async () => {
  sdk.capabilities.mockRejectedValue(new Error('Permissions unavailable.'));
  render(<HomePage />);
  await navigate('Operations');
  await navigate('Overview');
  await navigate('Operations');
  expect(sdk.health).toHaveBeenCalledOnce();
  expect(screen.getByRole('alert')).toHaveTextContent('Permission check failed: Permissions unavailable.');
  expect(screen.getByRole('button', { name: 'Request simulate' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Expire due rentals' })).toBeDisabled();
  expect(sdk.requestControl).not.toHaveBeenCalled();
});

it('restores the selected screen and its health read after a browser remount', async () => {
  const first = render(<HomePage />, { wrapper: withCache(createReadCache('operations-user')) });
  await navigate('Operations');
  first.unmount();
  now += 6 * 60_000;
  render(<HomePage />, { wrapper: withCache(createReadCache('operations-user')) });
  await act(async () => {});
  expect(screen.getByRole('heading', { name: 'Connection verification' })).toBeInTheDocument();
  expect(lastChecked()).toHaveAttribute('datetime', '2026-10-10T12:00:00.000Z');
  expect(sdk.health).toHaveBeenCalledOnce();
  expect(sdk.capabilities).toHaveBeenCalledTimes(2);
});

it('refreshes health with the topbar Refresh data button in the shared cache', async () => {
  render(<HomePage />, { wrapper: withCache(createReadCache('operations-refresh')) });
  await navigate('Operations');
  now += 6 * 60_000;
  sdk.health.mockResolvedValue({ ...health, outbox_pending: 0 });
  await navigate('Refresh data');
  expect(sdk.health).toHaveBeenCalledTimes(2);
  expect(lastChecked()).toHaveAttribute('datetime', '2026-10-10T12:06:00.000Z');
  await navigate('Check health');
  expect(sdk.health).toHaveBeenCalledTimes(3);
});

it('ignores an old health response after a command invalidates the active screen', async () => {
  const cache = createReadCache('health-command');
  const old = deferredHealth();
  sdk.health.mockReturnValueOnce(old.promise);
  render(<HomePage />, { wrapper: withCache(cache) });
  await navigate('Operations');
  sdk.health.mockResolvedValue({ ...health, database: 'Reconciled database' });
  await act(async () => { cache.invalidate('read:'); });
  expect(screen.getByText('Reconciled database')).toBeInTheDocument();
  await act(async () => { old.resolve({ ...health, database: 'Obsolete database' }); });
  expect(screen.queryByText('Obsolete database')).not.toBeInTheDocument();
  expect(screen.getByText('Reconciled database')).toBeInTheDocument();
  expect(sdk.health).toHaveBeenCalledTimes(2);
});
