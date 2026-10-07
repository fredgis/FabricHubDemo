import { afterEach, describe, expect, it, vi } from 'vitest';
import { createDemoPlan, DemoScenario, type DemoFunctions } from '../../apps/cockpit/src/domain/demo-scenario';

const references = {
  customers: [{ customer_key: 'MSF-C0001', territory: 'FR' }],
  offers: [
    { offer_key: 'SINTEL:FR:RENTAL', content_key: 'SINTEL', territory: 'FR', transaction_type: 'TVOD' },
    { offer_key: 'SINTEL:FR:PURCHASE', content_key: 'SINTEL', territory: 'FR', transaction_type: 'EST' },
  ],
  content: [{ content_key: 'SINTEL', duration_seconds: 888 }],
};

function boundary(): DemoFunctions {
  return {
    capabilities: { invoke: vi.fn(async () => ({ can_operate: true, reason: 'Time-bounded operator grant' })) },
    placeOrder: { invoke: vi.fn(async () => ({
      entity_key: 'actual-order', status: 'booked', event_ids: ['order-created'],
    })) },
    startPlayback: { invoke: vi.fn(async () => ({
      entity_key: 'actual-session', status: 'playing', event_ids: ['order-activated', 'playback-created'],
    })) },
    recordProgress: { invoke: vi.fn(async () => ({
      entity_key: 'actual-session', status: 'playing', event_ids: ['playback-updated'],
    })) },
  };
}

afterEach(() => vi.useRealTimers());

describe('bounded Demo typed command boundary', () => {
  it('retries a lost playback response with the identical key and input, not a new order', async () => {
    const functions = boundary();
    vi.mocked(functions.startPlayback.invoke)
      .mockRejectedValueOnce(new Error('Response lost after the playback committed.'))
      .mockResolvedValue({ entity_key: 'actual-session', status: 'playing', event_ids: ['order-activated', 'playback-created'] });
    const run = new DemoScenario(createDemoPlan({
      scenario: 'rental', count: 1, paceMs: 0, customerKey: 'MSF-C0001',
    }, references, 'retry-a'), functions);

    expect(await run.execute()).toMatchObject({ status: 'failed', completedTransactions: 0 });
    const retried = await run.execute();
    expect(retried.status).toBe('completed');
    expect(functions.placeOrder.invoke).toHaveBeenCalledOnce();
    expect(vi.mocked(functions.startPlayback.invoke).mock.calls).toEqual([
      [{ input: { order_id: 'actual-order', idempotency_key: 'demo:retry-a:0:play' } }],
      [{ input: { order_id: 'actual-order', idempotency_key: 'demo:retry-a:0:play' } }],
    ]);
    expect(retried.receipts.flatMap(row => row.result.event_ids)).toEqual([
      'order-created', 'order-activated', 'playback-created', 'playback-updated',
    ]);
  });

  it('does not create duplicate commands when execute is triggered twice', async () => {
    const functions = boundary();
    const run = new DemoScenario(createDemoPlan({
      scenario: 'purchase', count: 1, paceMs: 0, customerKey: 'MSF-C0001',
    }, references, 'double-a'), functions);
    const results = await Promise.all([run.execute(), run.execute()]);
    expect(results[0].receipts).toEqual(results[1].receipts);
    expect(functions.placeOrder.invoke).toHaveBeenCalledOnce();
    expect(functions.startPlayback.invoke).toHaveBeenCalledOnce();
    expect(functions.recordProgress.invoke).toHaveBeenCalledOnce();
  });

  it.each([0, 101, 1.5, NaN])('rejects out-of-bound journey count %s before any command', count => {
    expect(() => createDemoPlan({
      scenario: 'rental', count, paceMs: 0, customerKey: 'MSF-C0001',
    }, references, 'bounds-a')).toThrow('Journey count must be a whole number from 1 to 100.');
  });

  it('resolves mixed rentals/purchases only from existing offers in the selected customer territory', () => {
    const plan = createDemoPlan({
      scenario: 'mixed', count: 2, paceMs: 1000, customerKey: 'MSF-C0001',
    }, references, 'mixed-a');
    expect(plan.transactions.map(row => row.offerKey)).toEqual(['SINTEL:FR:RENTAL', 'SINTEL:FR:PURCHASE']);
    expect(() => createDemoPlan({
      scenario: 'rental', count: 1, paceMs: 0, customerKey: 'another-actor',
    }, references, 'unknown-a')).toThrow('Select an existing customer');
  });

  it('stops on a server-side actor denial without claiming success or attempting the next command', async () => {
    const functions = boundary();
    vi.mocked(functions.startPlayback.invoke).mockRejectedValue(new Error('Operator grant revoked.'));
    const run = new DemoScenario(createDemoPlan({
      scenario: 'rental', count: 1, paceMs: 0, customerKey: 'MSF-C0001',
    }, references, 'revoked-a'), functions);
    expect(await run.execute()).toMatchObject({
      status: 'failed', error: 'Operator grant revoked.', completedTransactions: 0,
      receipts: [{ command: 'placeOrder', result: { entity_key: 'actual-order' } }],
    });
    expect(functions.recordProgress.invoke).not.toHaveBeenCalled();
  });

  it('does not count or advance a malformed native command response as a persisted receipt', async () => {
    const functions = boundary();
    vi.mocked(functions.placeOrder.invoke).mockResolvedValue({
      entity_key: '', status: 'booked', event_ids: [],
    });
    const run = new DemoScenario(createDemoPlan({
      scenario: 'rental', count: 1, paceMs: 0, customerKey: 'MSF-C0001',
    }, references, 'invalid-a'), functions);

    expect(await run.execute()).toMatchObject({
      status: 'failed', error: 'Native function returned an invalid command receipt.', receipts: [],
    });
    expect(functions.startPlayback.invoke).not.toHaveBeenCalled();
  });

  it('paces native commands sequentially and cancels an outstanding pace wait immediately', async () => {
    vi.useFakeTimers();
    const functions = boundary();
    const run = new DemoScenario(createDemoPlan({
      scenario: 'rental', count: 1, paceMs: 500, customerKey: 'MSF-C0001',
    }, references, 'paced-a'), functions);
    const running = run.execute();
    await vi.advanceTimersByTimeAsync(0);
    expect(functions.placeOrder.invoke).toHaveBeenCalledOnce();
    expect(functions.startPlayback.invoke).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(499);
    expect(functions.startPlayback.invoke).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(functions.startPlayback.invoke).toHaveBeenCalledOnce();
    expect(functions.recordProgress.invoke).not.toHaveBeenCalled();
    run.cancel();
    expect((await running).status).toBe('cancelled');
    expect(functions.recordProgress.invoke).not.toHaveBeenCalled();
  });

  it('cancels at the command boundary, keeps an in-flight receipt, and resumes without repeating that order', async () => {
    const functions = boundary();
    let acceptOrder!: (value: Awaited<ReturnType<DemoFunctions['placeOrder']['invoke']>>) => void;
    vi.mocked(functions.placeOrder.invoke).mockReturnValue(new Promise(resolve => { acceptOrder = resolve; }));
    const run = new DemoScenario(createDemoPlan({
      scenario: 'rental', count: 1, paceMs: 0, customerKey: 'MSF-C0001',
    }, references, 'cancel-a'), functions);
    const running = run.execute();
    await vi.waitFor(() => expect(functions.placeOrder.invoke).toHaveBeenCalledOnce());
    run.cancel();
    acceptOrder({ entity_key: 'committed-order', status: 'booked', event_ids: ['committed-event'] });

    expect(await running).toMatchObject({
      status: 'cancelled', completedTransactions: 0,
      receipts: [{ command: 'placeOrder', result: { entity_key: 'committed-order', event_ids: ['committed-event'] } }],
    });
    expect(functions.startPlayback.invoke).not.toHaveBeenCalled();
    expect((await run.execute()).status).toBe('completed');
    expect(functions.placeOrder.invoke).toHaveBeenCalledOnce();
    expect(functions.startPlayback.invoke).toHaveBeenCalledWith({ input: {
      order_id: 'committed-order', idempotency_key: 'demo:cancel-a:0:play',
    } });
  });

  it('does not issue commands when the current actor capability is denied', async () => {
    const functions = boundary();
    vi.mocked(functions.capabilities.invoke).mockResolvedValue({
      can_operate: false, reason: 'Read-only viewer. Operator permission required.',
    });
    const run = new DemoScenario(createDemoPlan({
      scenario: 'rental', count: 1, paceMs: 0, customerKey: 'MSF-C0001',
    }, references, 'denied-actor'), functions);

    expect(await run.execute()).toMatchObject({
      status: 'failed', error: 'Read-only viewer. Operator permission required.', receipts: [],
    });
    expect(functions.placeOrder.invoke).not.toHaveBeenCalled();
    expect(functions.startPlayback.invoke).not.toHaveBeenCalled();
    expect(functions.recordProgress.invoke).not.toHaveBeenCalled();
  });

  it('persists a rental journey using server-returned order/session IDs and event receipts', async () => {
    const functions = boundary();
    const plan = createDemoPlan({
      scenario: 'rental', count: 1, paceMs: 0, customerKey: 'MSF-C0001',
    }, references, 'demo-a');
    const run = new DemoScenario(plan, functions);
    const result = await run.execute();

    expect(result.status).toBe('completed');
    expect(result.completedTransactions).toBe(1);
    expect(result.receipts.map(row => row.result)).toEqual([
      { entity_key: 'actual-order', status: 'booked', event_ids: ['order-created'] },
      { entity_key: 'actual-session', status: 'playing', event_ids: ['order-activated', 'playback-created'] },
      { entity_key: 'actual-session', status: 'playing', event_ids: ['playback-updated'] },
    ]);
    expect(functions.placeOrder.invoke).toHaveBeenCalledWith({ input: {
      customer_key: 'MSF-C0001', offer_key: 'SINTEL:FR:RENTAL', idempotency_key: 'demo:demo-a:0:order',
    } });
    expect(functions.startPlayback.invoke).toHaveBeenCalledWith({ input: {
      order_id: 'actual-order', idempotency_key: 'demo:demo-a:0:play',
    } });
    expect(functions.recordProgress.invoke).toHaveBeenCalledWith({ input: {
      session_id: 'actual-session', position_seconds: 60, idempotency_key: 'demo:demo-a:0:progress',
    } });
  });
});
