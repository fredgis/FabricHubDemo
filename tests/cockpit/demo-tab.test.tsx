import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';

vi.mock('../../apps/cockpit/src/hooks/AuthContext', () => ({
  useAuth: () => ({ user: { name: 'Demo viewer' }, signOut: vi.fn() }),
}));
vi.mock('../../apps/cockpit/src/services/rayfinClient', () => ({
  getRayfinClient: () => ({
    functions: { capabilities: { invoke: async () => ({ can_operate: false, reason: 'Viewer test actor.' }) } },
  }),
}));
vi.mock('../../apps/cockpit/src/services/source-reloads', async importOriginal => ({
  ...await importOriginal<typeof import('../../apps/cockpit/src/services/source-reloads')>(),
  readSourceReloads: async () => [],
}));
vi.mock('../../apps/cockpit/src/services/business', async importOriginal => {
  const original = await importOriginal<typeof import('../../apps/cockpit/src/services/business')>();
  return { ...original, loadSnapshot: async () => ({
    content: [], customers: [], offers: [], rentals: [], playback: [], outbox: [], commands: [],
    campaigns: [], members: [], links: [],
  }) };
});
import { HomePage } from '../../apps/cockpit/src/pages/HomePage';
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
});
