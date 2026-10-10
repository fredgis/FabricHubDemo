import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Snapshot } from '../../apps/cockpit/src/services/business';
import type { AppFunctionsSchema } from '../../apps/cockpit/rayfin/functions/src/types';

const sdk = vi.hoisted(() => ({
  functions: {
    capabilities: { invoke: vi.fn() },
    placeOrder: { invoke: vi.fn() },
    startPlayback: { invoke: vi.fn() },
    recordProgress: { invoke: vi.fn() },
    health: { invoke: vi.fn() },
  },
}));
vi.mock('../../apps/cockpit/src/services/rayfinClient', () => ({ getRayfinClient: () => sdk }));
vi.mock('../../apps/cockpit/src/services/source-reloads', async importOriginal => ({
  ...await importOriginal<typeof import('../../apps/cockpit/src/services/source-reloads')>(),
  readSourceReloads: async () => [],
}));
import { DemoPage } from '../../apps/cockpit/src/pages/DemoPage';

const snapshot = {
  content: [{ content_key: 'SINTEL', title: 'Sintel', duration_seconds: 888 }],
  customers: [{ customer_key: 'MSF-C0001', name: 'Fictional customer', territory: 'FR' }],
  offers: [
    { offer_key: 'SINTEL:FR:RENTAL', content_key: 'SINTEL', territory: 'FR', transaction_type: 'TVOD' },
    { offer_key: 'SINTEL:FR:PURCHASE', content_key: 'SINTEL', territory: 'FR', transaction_type: 'EST' },
  ],
  rentals: [], playback: [], outbox: [], commands: [], campaigns: [], members: [], links: [],
} as Snapshot;

beforeEach(() => {
  vi.resetAllMocks();
  sdk.functions.capabilities.invoke.mockResolvedValue({ can_operate: true, reason: 'Time-bounded operator grant' });
  sdk.functions.placeOrder.invoke.mockResolvedValue({ entity_key: 'actual-order', status: 'booked', event_ids: ['order-created'] });
  sdk.functions.startPlayback.invoke.mockResolvedValue({
    entity_key: 'actual-session', status: 'playing', event_ids: ['order-activated', 'playback-created'],
  });
  sdk.functions.recordProgress.invoke.mockResolvedValue({
    entity_key: 'actual-session', status: 'playing', event_ids: ['playback-updated'],
  });
  sdk.functions.health.invoke.mockResolvedValue({
    database: 'Verified operational SQL', functions: 'Native UDF invocation verified', outbox_pending: 4,
    broker: 'Acknowledgements are recorded by the external publisher.',
  });
});
afterEach(cleanup);

describe('dedicated Demo controls', () => {
  it('shares the total journeys across random customers and remembers the fixed customer selection', async () => {
    const varied = { ...snapshot,
      customers: [...snapshot.customers, { ...snapshot.customers[0], customer_key: 'MSF-C0002', name: 'Second fictional customer' }],
      content: [...snapshot.content, { ...snapshot.content[0], content_key: 'BUNNY', title: 'Big Buck Bunny', duration_seconds: 30 }],
      offers: [...snapshot.offers, { ...snapshot.offers[0], offer_key: 'BUNNY:FR:RENTAL', content_key: 'BUNNY' }],
    };
    render(<DemoPage snapshot={varied} capabilities={{ can_operate: true, reason: 'Operator grant' }} onRefresh={vi.fn()} />);
    fireEvent.change(screen.getByRole('combobox', { name: 'Existing customer' }), { target: { value: 'MSF-C0002' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Customer selection' }), { target: { value: 'random' } });
    expect(screen.queryByRole('combobox', { name: 'Existing customer' })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Random customer count' }), { target: { value: '2' } });
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Journey count' }), { target: { value: '5' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Pace between commands' }), { target: { value: '0' } });
    expect(sdk.functions.placeOrder.invoke).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Start demo' }));
    await screen.findByText('All 5 journeys completed.');

    const orders = sdk.functions.placeOrder.invoke.mock.calls.map(([request]) => request.input);
    expect(orders).toHaveLength(5);
    expect(new Set(orders.map(row => row.customer_key))).toEqual(new Set(['MSF-C0001', 'MSF-C0002']));
    expect(new Set(orders.map(row => row.offer_key))).toEqual(new Set(['SINTEL:FR:RENTAL', 'BUNNY:FR:RENTAL']));
    expect(screen.getByText('2 distinct customers in this run.')).toBeInTheDocument();
    expect(screen.getAllByText('Customer: MSF-C0001').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Customer: MSF-C0002').length).toBeGreaterThan(0);
    fireEvent.change(screen.getByRole('combobox', { name: 'Customer selection' }), { target: { value: 'fixed' } });
    expect(screen.getByRole('combobox', { name: 'Existing customer' })).toHaveValue('MSF-C0002');
    expect(screen.queryByRole('spinbutton', { name: 'Random customer count' })).not.toBeInTheDocument();
    expect(sdk.functions.placeOrder.invoke).toHaveBeenCalledTimes(5);
  });

  it('links random-customer bounds and eligibility errors without issuing commands', async () => {
    const capabilities = { can_operate: true, reason: 'Operator grant' };
    const onRefresh = vi.fn();
    const view = render(<DemoPage snapshot={snapshot} capabilities={capabilities} onRefresh={onRefresh} />);
    await screen.findByText('Oracle: no persisted reload request');
    fireEvent.change(screen.getByRole('combobox', { name: 'Customer selection' }), { target: { value: 'random' } });
    const customerCount = screen.getByRole('spinbutton', { name: 'Random customer count' });
    expect(customerCount).toHaveValue(1);
    fireEvent.change(customerCount, { target: { value: '2' } });
    expect(customerCount).toHaveAttribute('aria-invalid', 'true');
    expect(customerCount).toHaveAccessibleDescription('Random customer count exceeds the eligible customer count (1).');
    expect(screen.getByRole('button', { name: 'Start demo' })).toBeDisabled();
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Journey count' }), { target: { value: '1' } });
    expect(customerCount).toHaveAttribute('max', '1');
    expect(customerCount).toHaveAccessibleDescription('Random customer count must be a whole number from 1 to the journey count.');
    fireEvent.change(customerCount, { target: { value: '1' } });
    expect(customerCount).not.toHaveAttribute('aria-invalid');
    expect(screen.getByRole('button', { name: 'Start demo' })).toBeEnabled();
    view.rerender(<DemoPage snapshot={{ ...snapshot, offers: [] }} capabilities={capabilities} onRefresh={onRefresh} />);
    expect(customerCount).toHaveAccessibleDescription('No existing customers have eligible offers for this scenario.');
    expect(screen.getByRole('button', { name: 'Start demo' })).toBeDisabled();
    expect(sdk.functions.placeOrder.invoke).not.toHaveBeenCalled();
  });

  it('renders actual receipt IDs while keeping generated, Kafka ACK, and Gold evidence separate', async () => {
    const onRefresh = vi.fn();
    const capabilities = { can_operate: true, reason: 'Time-bounded operator grant' };
    const view = render(<DemoPage snapshot={snapshot} capabilities={capabilities} onRefresh={onRefresh} />);
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Journey count' }), { target: { value: '1' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Pace between commands' }), { target: { value: '0' } });
    fireEvent.click(screen.getByRole('button', { name: 'Start demo' }));
    await screen.findByText('All 1 journeys completed.');

    expect(screen.getByText('actual-order')).toBeInTheDocument();
    for (const id of ['order-created', 'order-activated', 'playback-created', 'playback-updated'])
      expect(screen.getByText(id)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Generated' }).parentElement).toHaveTextContent('4');
    expect(screen.getByRole('heading', { name: 'Kafka ACK' }).parentElement).toHaveTextContent('0 of 4');
    expect(screen.getByRole('heading', { name: 'Gold published' }).parentElement).toHaveTextContent('Not read yet');

    fireEvent.click(screen.getByRole('button', { name: 'Refresh receipts & publication' }));
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Kafka ACK' }).parentElement)
      .toHaveTextContent(/Outbox pending:\s*4/));
    expect(onRefresh).toHaveBeenCalledOnce();
    expect(sdk.functions.health.invoke).toHaveBeenCalledOnce();
    expect(sdk.functions.placeOrder.invoke).toHaveBeenCalledOnce();

    const gold = {
      dashboard: {
        source: { name: 'MSFlixGold', workspace_id: 'workspace', item_id: 'gold', views: [] },
        state: 'ready', freshness: { queried_at: '2026-10-07T21:00:00Z', published_at: '2026-10-07T20:45:00Z',
          publication_run_id: 'actual-publication', order_lines: '1002' },
        commercial: [], playback: [], campaigns: [], dimensions: { customers: '700', content: '305' },
      },
      catalog: [], customers: [], offers: [], orders: [{ order_id: 'older-order' }],
      sessions: [], campaigns: [], window: { orders: 500, sessions: 500, references: 1000 },
    } satisfies AppFunctionsSchema['businessViews']['output'];
    const observed = { ...snapshot, outbox: [
      { event_id: 'order-created', published_at: new Date('2026-10-07T21:01:00Z') },
      { event_id: 'playback-created' },
    ] } as Snapshot;
    view.rerender(<DemoPage snapshot={observed} capabilities={capabilities} onRefresh={onRefresh} gold={gold} />);
    expect(screen.getByRole('heading', { name: 'Kafka ACK' }).parentElement).toHaveTextContent('1 of 4');
    expect(screen.getByRole('heading', { name: 'Kafka ACK' }).parentElement)
      .toHaveTextContent('1 observed pending · 2 not observed');
    const publication = screen.getByRole('heading', { name: 'Gold published' }).parentElement;
    expect(publication).toHaveTextContent('Published');
    expect(publication).toHaveTextContent('0 of 1 run orders and 0 of 1 run sessions observed');
    expect(publication).toHaveTextContent('Event-level publication is not verified for this run.');
  });

  it('uses the Cancel and Resume controls without repeating the in-flight persisted order', async () => {
    let accept!: (value: { entity_key: string; status: string; event_ids: string[] }) => void;
    sdk.functions.placeOrder.invoke.mockReturnValue(new Promise(resolve => { accept = resolve; }));
    render(<DemoPage snapshot={snapshot} capabilities={{ can_operate: true, reason: 'Operator grant' }}
      onRefresh={vi.fn()} />);
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Journey count' }), { target: { value: '1' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Pace between commands' }), { target: { value: '0' } });
    fireEvent.click(screen.getByRole('button', { name: 'Start demo' }));
    await waitFor(() => expect(sdk.functions.placeOrder.invoke).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByRole('button', { name: 'Cancel demo' }));
    accept({ entity_key: 'accepted-order', status: 'booked', event_ids: ['accepted-event'] });
    await screen.findByText('Demo cancelled at a command boundary.');
    expect(screen.getByText('accepted-order')).toBeInTheDocument();
    expect(sdk.functions.startPlayback.invoke).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Resume same run' }));
    await screen.findByText('All 1 journeys completed.');
    expect(sdk.functions.placeOrder.invoke).toHaveBeenCalledOnce();
    expect(sdk.functions.startPlayback.invoke).toHaveBeenCalledWith({
      input: { order_id: 'accepted-order', idempotency_key: expect.any(String) },
    });
  });

  it('continues an in-flight Demo while inactive and retains failed-command retry keys on return', async () => {
    let accept!: (value: { entity_key: string; status: string; event_ids: string[] }) => void;
    sdk.functions.placeOrder.invoke.mockReturnValueOnce(new Promise(resolve => { accept = resolve; }));
    sdk.functions.startPlayback.invoke.mockRejectedValueOnce(new Error('Playback response lost'));
    const capabilities = { can_operate: true, reason: 'Operator grant' };
    const onRefresh = vi.fn();
    const view = render(<DemoPage active snapshot={snapshot} capabilities={capabilities} onRefresh={onRefresh} />);
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Journey count' }), { target: { value: '1' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Pace between commands' }), { target: { value: '0' } });
    fireEvent.click(screen.getByRole('button', { name: 'Start demo' }));
    view.rerender(<DemoPage active={false} snapshot={null} capabilities={capabilities} onRefresh={onRefresh} />);
    await act(async () => { accept({ entity_key: 'persisted-order', status: 'booked', event_ids: ['persisted-event'] }); });
    await screen.findByText('Demo paused on a command failure.');
    expect(sdk.functions.startPlayback.invoke).toHaveBeenCalledOnce();
    const firstPlayback = sdk.functions.startPlayback.invoke.mock.calls[0][0];
    view.rerender(<DemoPage active snapshot={snapshot} capabilities={capabilities} onRefresh={onRefresh} />);
    fireEvent.click(screen.getByRole('button', { name: 'Retry same run' }));
    await screen.findByText('All 1 journeys completed.');
    expect(sdk.functions.placeOrder.invoke).toHaveBeenCalledOnce();
    expect(sdk.functions.startPlayback.invoke.mock.calls[1][0]).toEqual(firstPlayback);
    expect(sdk.functions.recordProgress.invoke).toHaveBeenCalledOnce();
    expect(sdk.functions.health.invoke).not.toHaveBeenCalled();
    expect(onRefresh).not.toHaveBeenCalled();
  });

  it('shows native health errors and never treats the read-only refresh as event generation', async () => {
    sdk.functions.health.invoke.mockRejectedValue(new Error('Native health access denied.'));
    render(<DemoPage snapshot={snapshot} capabilities={{ can_operate: true, reason: 'Operator grant' }}
      onRefresh={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Refresh receipts & publication' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Health read failed: Native health access denied.');
    expect(screen.getByRole('heading', { name: 'Kafka ACK' }).parentElement).toHaveTextContent('Outbox pending: Not read yet');
    expect(sdk.functions.placeOrder.invoke).not.toHaveBeenCalled();
  });

  it('disables submission and links the validation message for a journey count above 100', async () => {
    render(<DemoPage snapshot={snapshot} capabilities={{ can_operate: true, reason: 'Operator grant' }}
      onRefresh={vi.fn()} />);
    await screen.findByText('Oracle: no persisted reload request');
    const count = screen.getByRole('spinbutton', { name: 'Journey count' });
    fireEvent.change(count, { target: { value: '101' } });
    expect(count).toHaveAttribute('aria-invalid', 'true');
    expect(count).toHaveAccessibleDescription('Journey count must be a whole number from 1 to 100.');
    expect(screen.getByRole('button', { name: 'Start demo' })).toBeDisabled();
    expect(sdk.functions.placeOrder.invoke).not.toHaveBeenCalled();
  });

  it('defaults to ten bounded journeys and never grants command permissions to a viewer', async () => {
    render(<DemoPage snapshot={snapshot} capabilities={{ can_operate: false, reason: 'Read-only viewer.' }}
      onRefresh={vi.fn()} />);
    await screen.findByText('Oracle: no persisted reload request');
    expect(screen.getByRole('spinbutton', { name: 'Journey count' })).toHaveValue(10);
    expect(screen.getByRole('spinbutton', { name: 'Journey count' })).toHaveAttribute('min', '1');
    expect(screen.getByRole('spinbutton', { name: 'Journey count' })).toHaveAttribute('max', '100');
    expect(screen.getByRole('button', { name: 'Start demo' })).toBeDisabled();
    expect(screen.getByText('Demo is read-only: Read-only viewer.')).toBeInTheDocument();
    expect(sdk.functions.placeOrder.invoke).not.toHaveBeenCalled();
  });
});
