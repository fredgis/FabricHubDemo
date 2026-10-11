import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { Snapshot } from '../../apps/cockpit/src/services/business';
import type { CommandResult } from '../../apps/cockpit/rayfin/functions/src/domain';

const sdk = vi.hoisted(() => ({ read: vi.fn(), placeOrder: vi.fn() }));
vi.mock('../../apps/cockpit/src/hooks/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'fixture-operator', name: 'Fixture operator' }, signOut: vi.fn() }),
}));
vi.mock('../../apps/cockpit/src/services/business', async importOriginal => ({
  ...await importOriginal<typeof import('../../apps/cockpit/src/services/business')>(), loadSnapshot: sdk.read,
}));
vi.mock('../../apps/cockpit/src/services/goldViews', () => ({
  loadGoldViews: async () => { throw new Error('Gold is outside this fixture'); },
}));
vi.mock('../../apps/cockpit/src/services/rayfinClient', () => ({
  getRayfinClient: () => ({ functions: {
    capabilities: { invoke: async () => ({ can_operate: true, reason: 'Fixture operator' }) },
    placeOrder: { invoke: sdk.placeOrder },
  } }),
}));
import { HomePage } from '../../apps/cockpit/src/pages/HomePage';

const snapshot = {
  content: [{ id: 'fixture-film', content_key: 'fixture-film', title: 'Fixture film', duration_seconds: 3600 }],
  customers: [{ id: 'fixture-customer', customer_key: 'fixture-customer', name: 'Fixture customer', territory: 'FR' }],
  offers: [{ id: 'fixture-offer', offer_key: 'fixture-offer', content_key: 'fixture-film', territory: 'FR',
    currency: 'EUR', transaction_type: 'TVOD', price_minor: 500, start_window_hours: 48, play_window_hours: 24 }],
  rentals: [], playback: [], outbox: [], commands: [], campaigns: [], members: [], links: [],
} as unknown as Snapshot;
const receipt = { status: 'booked', entity_key: 'fixture-order', event_ids: ['fixture-event'] } as CommandResult;
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
beforeEach(() => {
  sdk.read.mockReset(); sdk.read.mockResolvedValue(snapshot);
  sdk.placeOrder.mockReset(); sdk.placeOrder.mockResolvedValue(receipt);
});
afterEach(cleanup);
async function openOrderForm() {
  render(<HomePage />);
  fireEvent.click(within(screen.getByRole('navigation', { name: 'Main navigation' }))
    .getByRole('button', { name: 'Rentals & Purchases' }));
  const button = await screen.findByRole('button', { name: 'Record order' });
  fireEvent.change(screen.getByLabelText('CRM customer'), { target: { value: 'fixture-customer' } });
  fireEvent.change(screen.getByLabelText('Available offer'), { target: { value: 'fixture-offer' } });
  await waitFor(() => expect(button).toBeEnabled());
  return button.closest('form')!;
}

it('confirms persistence before a slow refresh finishes while blocking a duplicate command', async () => {
  const form = await openOrderForm();
  const mutation = deferred<CommandResult>();
  const reload = deferred<Snapshot>();
  sdk.placeOrder.mockReturnValueOnce(mutation.promise);
  sdk.read.mockReturnValueOnce(reload.promise);
  fireEvent.submit(form);
  expect(screen.getByRole('button', { name: 'Persisting…' })).toBeDisabled();
  fireEvent.submit(form);
  expect(sdk.placeOrder).toHaveBeenCalledOnce();
  await act(async () => { mutation.resolve(receipt); await mutation.promise; });
  expect(screen.getByText('Command persisted: booked')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Record order' })).toBeDisabled();
  expect(screen.queryByRole('button', { name: 'Persisting…' })).not.toBeInTheDocument();
  fireEvent.submit(form);
  expect(sdk.placeOrder).toHaveBeenCalledOnce();
  await act(async () => { reload.resolve(snapshot); await reload.promise; });
  expect(screen.getByRole('button', { name: 'Record order' })).toBeEnabled();
});

it('keeps the receipt on refresh failure, reports a read error and requires a successful re-read', async () => {
  const form = await openOrderForm();
  sdk.read.mockRejectedValueOnce(new Error('Fixture refresh unavailable'));
  fireEvent.submit(form);
  await screen.findByText('Command persisted: booked');
  await screen.findByText(/Refresh failed.*Fixture refresh unavailable/);
  expect(screen.queryByText(/Retrying the same command reuses/)).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Record order' })).toBeDisabled();
  fireEvent.submit(form);
  expect(sdk.placeOrder).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole('button', { name: 'Refresh data' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Record order' })).toBeEnabled());
  fireEvent.submit(form);
  await waitFor(() => expect(sdk.placeOrder).toHaveBeenCalledTimes(2));
  const [first, second] = sdk.placeOrder.mock.calls.map(([args]) => args.input.idempotency_key);
  expect(second).not.toBe(first);
});

it('reuses the idempotency key after a failed mutation and does not refresh failed commands', async () => {
  const form = await openOrderForm();
  sdk.placeOrder.mockRejectedValueOnce(new Error('Fixture mutation failed'));
  fireEvent.submit(form);
  await screen.findByText(/Fixture mutation failed.*Retrying the same command reuses/);
  expect(sdk.read).toHaveBeenCalledOnce();
  expect(screen.queryByText('Command persisted: booked')).not.toBeInTheDocument();
  fireEvent.submit(form);
  await screen.findByText('Command persisted: booked');
  const [first, second] = sdk.placeOrder.mock.calls.map(([args]) => args.input.idempotency_key);
  expect(second).toBe(first);
  expect(sdk.read).toHaveBeenCalledTimes(2);
});

function ledgerPage(ordersPage = 1, playbackPage = 1): Snapshot {
  return { ...snapshot,
    rentals: [{ id: `fixture-order-${ordersPage}`, order_id: `fixture-order-${ordersPage}`,
      customer_key: 'fixture-customer', offer_key: 'fixture-offer', status: 'booked', amount_minor: 500,
      currency: 'EUR', created_at: new Date('2026-10-11T08:00:00Z'), start_deadline: null,
      first_play_at: null, expires_at: null }],
    playback: [{ id: `fixture-session-${playbackPage}`, session_id: `fixture-session-${playbackPage}`,
      order_id: 'fixture-order-1', customer_key: 'fixture-customer', content_key: 'fixture-film',
      status: 'paused', position_seconds: 30 }],
    pagination: { orders: { page: ordersPage, pageSize: 50, total: 51 },
      sessions: { page: playbackPage, pageSize: 50, total: 101 } },
  };
}

it('pages both ledgers independently, keeps the form mounted and blocks writes during page reads', async () => {
  sdk.read.mockResolvedValueOnce(ledgerPage());
  const form = await openOrderForm();
  expect(within(screen.getByRole('navigation', { name: 'Orders pagination' })).getByText(/Orders: 51 total/)).toBeInTheDocument();
  expect(within(screen.getByRole('navigation', { name: 'Playback pagination' })).getByText(/Playback: 101 total/)).toBeInTheDocument();
  const next = deferred<Snapshot>();
  sdk.read.mockReturnValueOnce(next.promise);
  fireEvent.click(screen.getByRole('button', { name: 'Next orders page' }));
  expect(screen.getByText('fixture-order-1')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Next orders page' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Next playback page' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Record order' })).toBeDisabled();
  fireEvent.submit(form);
  expect(sdk.placeOrder).not.toHaveBeenCalled();
  await act(async () => { next.resolve(ledgerPage(2)); });
  expect(screen.getByText('fixture-order-2')).toBeInTheDocument();
  expect(screen.queryByText('fixture-order-1')).not.toBeInTheDocument();
  expect(screen.getByLabelText('CRM customer')).toHaveValue('fixture-customer');
  expect(screen.getByLabelText('Available offer')).toHaveValue('fixture-offer');
  expect(screen.getByRole('button', { name: 'Record order' }).closest('form')).toBe(form);
  expect(screen.getByRole('button', { name: 'Next orders page' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Previous orders page' })).toBeEnabled();
  sdk.read.mockResolvedValueOnce(ledgerPage(2, 2));
  fireEvent.click(screen.getByRole('button', { name: 'Next playback page' }));
  await waitFor(() => expect(within(screen.getByRole('navigation', { name: 'Playback pagination' }))
    .getByText('Page 2 of 3')).toBeInTheDocument());
  expect(sdk.read.mock.calls.at(-1)?.[1]).toMatchObject({ ordersPage: 2, playbackPage: 2 });
  expect(within(screen.getByRole('navigation', { name: 'Orders pagination' })).getByText('Page 2 of 2')).toBeInTheDocument();
  sdk.read.mockResolvedValueOnce(ledgerPage(1, 2));
  fireEvent.click(screen.getByRole('button', { name: 'Previous orders page' }));
  await screen.findByText('fixture-order-1');
  expect(sdk.read.mock.calls.at(-1)?.[1]).toMatchObject({ ordersPage: 1, playbackPage: 2 });
});

it('retains the last good ledger after a failed page read and recovers through Refresh data', async () => {
  sdk.read.mockResolvedValueOnce(ledgerPage());
  const form = await openOrderForm();
  sdk.read.mockRejectedValueOnce(new Error('Fixture page unavailable'));
  fireEvent.click(screen.getByRole('button', { name: 'Next orders page' }));
  await screen.findByText(/Refresh failed.*Fixture page unavailable/);
  expect(screen.getByText('fixture-order-1')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Next orders page' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Next playback page' })).toBeDisabled();
  fireEvent.submit(form);
  expect(sdk.placeOrder).not.toHaveBeenCalled();
  sdk.read.mockResolvedValueOnce(ledgerPage(2));
  fireEvent.click(screen.getByRole('button', { name: 'Refresh data' }));
  await screen.findByText('fixture-order-2');
  expect(sdk.read).toHaveBeenLastCalledWith('orders', { ordersPage: 2, playbackPage: 1 });
  expect(screen.getByRole('button', { name: 'Record order' })).toBeEnabled();
  expect(screen.queryByText(/Refresh failed/)).not.toBeInTheDocument();
});

it('shows empty server totals with both page controls disabled', async () => {
  sdk.read.mockResolvedValueOnce({ ...snapshot, pagination: {
    orders: { page: 1, pageSize: 50, total: 0 }, sessions: { page: 1, pageSize: 50, total: 0 },
  } });
  await openOrderForm();
  for (const name of ['Orders pagination', 'Playback pagination']) {
    const pager = within(screen.getByRole('navigation', { name }));
    expect(pager.getByText(/: 0 total/)).toBeInTheDocument();
    expect(pager.getByText('Page 1 of 1')).toBeInTheDocument();
    for (const button of pager.getAllByRole('button')) expect(button).toBeDisabled();
  }
});
