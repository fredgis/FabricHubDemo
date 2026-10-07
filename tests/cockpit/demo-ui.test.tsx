import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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

  it('shows native health errors and never treats the read-only refresh as event generation', async () => {
    sdk.functions.health.invoke.mockRejectedValue(new Error('Native health access denied.'));
    render(<DemoPage snapshot={snapshot} capabilities={{ can_operate: true, reason: 'Operator grant' }}
      onRefresh={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Refresh receipts & publication' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Health read failed: Native health access denied.');
    expect(screen.getByRole('heading', { name: 'Kafka ACK' }).parentElement).toHaveTextContent('Outbox pending: Not read yet');
    expect(sdk.functions.placeOrder.invoke).not.toHaveBeenCalled();
  });

  it('disables submission and links the validation message for a journey count above 100', () => {
    render(<DemoPage snapshot={snapshot} capabilities={{ can_operate: true, reason: 'Operator grant' }}
      onRefresh={vi.fn()} />);
    const count = screen.getByRole('spinbutton', { name: 'Journey count' });
    fireEvent.change(count, { target: { value: '101' } });
    expect(count).toHaveAttribute('aria-invalid', 'true');
    expect(count).toHaveAccessibleDescription('Journey count must be a whole number from 1 to 100.');
    expect(screen.getByRole('button', { name: 'Start demo' })).toBeDisabled();
    expect(sdk.functions.placeOrder.invoke).not.toHaveBeenCalled();
  });

  it('defaults to ten bounded journeys and never grants command permissions to a viewer', () => {
    render(<DemoPage snapshot={snapshot} capabilities={{ can_operate: false, reason: 'Read-only viewer.' }}
      onRefresh={vi.fn()} />);
    expect(screen.getByRole('spinbutton', { name: 'Journey count' })).toHaveValue(10);
    expect(screen.getByRole('spinbutton', { name: 'Journey count' })).toHaveAttribute('min', '1');
    expect(screen.getByRole('spinbutton', { name: 'Journey count' })).toHaveAttribute('max', '100');
    expect(screen.getByRole('button', { name: 'Start demo' })).toBeDisabled();
    expect(screen.getByText('Demo is read-only: Read-only viewer.')).toBeInTheDocument();
    expect(sdk.functions.placeOrder.invoke).not.toHaveBeenCalled();
  });
});
