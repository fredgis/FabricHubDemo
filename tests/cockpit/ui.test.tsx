import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
vi.mock('../../apps/cockpit/src/hooks/AuthContext', () => ({
  useAuth: () => ({ user: { name: 'Test operator' }, signOut: vi.fn() }),
}));
vi.mock('../../apps/cockpit/src/services/rayfinClient', () => ({
  getRayfinClient: () => ({ functions: { capabilities: { invoke: async () => ({ can_operate: false, reason: 'Read-only viewer' }) } } }),
}));
vi.mock('../../apps/cockpit/src/services/business', async importOriginal => {
  const original = await importOriginal<typeof import('../../apps/cockpit/src/services/business')>();
  return { ...original, loadSnapshot: async () => ({
    content: [], customers: [], offers: [], rentals: [], playback: [], outbox: [], commands: [],
    campaigns: [], members: [], links: [],
  }) };
});
import { Artwork, Empty, ErrorState, HomePage, LoadingState } from '../../apps/cockpit/src/pages/HomePage';
import type { Content } from '../../apps/cockpit/rayfin/data/schema';
afterEach(cleanup);
describe('honest accessible UI states', () => {
  it('explains empty data without invented KPIs', () => {
    render(<Empty title="No orders yet">Record an authorized transaction.</Empty>);
    expect(screen.getByRole('heading', { name: 'No orders yet' })).toBeInTheDocument();
    expect(screen.getByText('Record an authorized transaction.')).toBeInTheDocument();
    expect(screen.queryByText('Connected')).not.toBeInTheDocument();
  });
  it('announces a actual connection failure and offers a working retry', () => {
    const retry = vi.fn();
    render(<ErrorState message="Operational SQL is not bound." retry={retry} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Operational SQL is not bound');
    fireEvent.click(screen.getByRole('button', { name: 'Retry connection' }));
    expect(retry).toHaveBeenCalledOnce();
  });
  it('announces data loading instead of showing success-shaped values', () => {
    render(<LoadingState />);
    expect(screen.getByRole('status')).toHaveTextContent('Reading persisted business activity');
    expect(screen.getByLabelText('Loading MSFlix data')).toHaveAttribute('aria-busy', 'true');
  });
  it('keeps commerce disabled for an actual viewer capability result', async () => {
    render(<HomePage />);
    await screen.findByText('Read-only viewer');
    fireEvent.click(screen.getByRole('button', { name: 'Rentals & Purchases' }));
    expect(await screen.findByRole('button', { name: 'Record order' })).toBeDisabled();
    expect(screen.getByText(/Operator permission is required/)).toBeInTheDocument();
  });
  it('labels unavailable artwork explicitly instead of inventing a film photo', () => {
    render(<Artwork film={{ title: 'Actual sourced film', image_url: '/catalog-unavailable.svg',
      artwork_available: false } as Content} />);
    expect(screen.getByText('Visuel non disponible')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Visuel non disponible : Actual sourced film' })).toBeInTheDocument();
    expect(screen.queryByAltText('Actual sourced film film artwork')).not.toBeInTheDocument();
  });
});
