import { afterEach, describe, expect, it, vi } from 'vitest';
import { createDemoPlan, DemoScenario, validateDemoConfig, type DemoFunctions } from '../../apps/cockpit/src/domain/demo-scenario';

const references = {
  customers: [{ customer_key: 'MSF-C0001', territory: 'FR' }],
  offers: [
    { offer_key: 'SINTEL:FR:RENTAL', content_key: 'SINTEL', territory: 'FR', transaction_type: 'TVOD' },
    { offer_key: 'SINTEL:FR:PURCHASE', content_key: 'SINTEL', territory: 'FR', transaction_type: 'EST' },
  ],
  content: [{ content_key: 'SINTEL', duration_seconds: 888 }],
};

const variedReferences = {
  customers: [
    ...references.customers,
    { customer_key: 'MSF-C0002', territory: 'FR' },
    { customer_key: 'MSF-C0003', territory: 'GB' },
    { customer_key: 'MSF-C0004', territory: 'GB' },
    { customer_key: 'MSF-C0005', territory: 'ES' },
    { customer_key: 'MSF-C0006', territory: 'DE' },
    ...references.customers,
  ],
  content: [...references.content, { content_key: 'BUNNY', duration_seconds: 30 }, { content_key: 'BROKEN', duration_seconds: 0 }],
  offers: [
    ...['FR', 'GB'].flatMap(territory => ['SINTEL', 'BUNNY'].flatMap(content_key =>
      ['TVOD', 'EST'].map(transaction_type => ({
        offer_key: `${content_key}:${territory}:${transaction_type}`, content_key, territory, transaction_type,
      })))),
    { offer_key: 'SINTEL:ES:TVOD', content_key: 'SINTEL', territory: 'ES', transaction_type: 'TVOD' },
    { offer_key: 'BROKEN:DE:TVOD', content_key: 'BROKEN', territory: 'DE', transaction_type: 'TVOD' },
    { offer_key: 'MISSING:FR:TVOD', content_key: 'MISSING', territory: 'FR', transaction_type: 'TVOD' },
  ],
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

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe('bounded Demo typed command boundary', () => {
  it.each(['rental', 'purchase', 'mixed'] as const)('chooses exactly N distinct eligible customers and random films for %s', scenario => {
    vi.spyOn(Math, 'random').mockReturnValue(0);
    const plan = createDemoPlan({
      scenario, count: 7, paceMs: 0, customerMode: 'random', customerCount: 3,
    }, variedReferences, 'random-a');
    expect(plan.transactions).toHaveLength(7);
    expect(new Set(plan.transactions.map(row => row.customerKey)))
      .toEqual(new Set(['MSF-C0002', 'MSF-C0003', 'MSF-C0004']));
    plan.transactions.forEach((row, index) => {
      const customer = variedReferences.customers.find(customer => customer.customer_key === row.customerKey)!;
      const transactionType = scenario === 'purchase' || (scenario === 'mixed' && index % 2 === 1) ? 'EST' : 'TVOD';
      expect(variedReferences.offers.find(offer => offer.offer_key === row.offerKey)).toMatchObject({
        content_key: row.contentKey, territory: customer.territory, transaction_type: transactionType,
      });
      expect(row.transactionType).toBe(transactionType);
      expect(row.progressSeconds).toBe(row.contentKey === 'BUNNY' ? 30 : 60);
      expect(['BUNNY', 'SINTEL']).toContain(row.contentKey);
      if (index) expect(row.contentKey).not.toBe(plan.transactions[index - 1].contentKey);
    });
  });

  it.each([0, -1, 1.5, NaN, Infinity, 4, 101])('rejects invalid random customer count %s', customerCount => {
    expect(() => createDemoPlan({
      scenario: 'rental', count: 3, paceMs: 0, customerMode: 'random', customerCount,
    }, variedReferences, 'customer-bounds')).toThrow('Random customer count must be a whole number from 1 to the journey count.');
  });

  it('rejects requests above the distinct eligible customer count and scenarios without eligible customers', () => {
    const config = { scenario: 'mixed' as const, count: 2, paceMs: 0, customerMode: 'random' as const, customerCount: 2 };
    expect(() => createDemoPlan(config, { ...references, customers: [...references.customers, ...references.customers] }, 'too-many'))
      .toThrow('Random customer count exceeds the eligible customer count (1).');
    for (const unavailable of [
      { ...references, customers: [] },
      { ...references, content: [{ content_key: 'SINTEL', duration_seconds: 0 }] },
      { ...references, offers: [references.offers[0]] },
    ]) {
      expect(() => createDemoPlan({ ...config, customerCount: 1 }, unavailable, 'no-eligible'))
        .toThrow('No existing customers have eligible offers for this scenario.');
    }
  });

  it('validates without drawing randomness and preserves the fixed-customer offer rotation', () => {
    const random = vi.spyOn(Math, 'random').mockReturnValue(0.99);
    validateDemoConfig({ scenario: 'rental', count: 4, paceMs: 0, customerMode: 'random', customerCount: 2 }, variedReferences);
    const plan = createDemoPlan({ scenario: 'mixed', count: 4, paceMs: 0, customerKey: 'MSF-C0001' }, variedReferences, 'fixed');
    expect(random).not.toHaveBeenCalled();
    expect(new Set(plan.transactions.map(row => row.customerKey))).toEqual(new Set(['MSF-C0001']));
    expect(plan.transactions.map(row => row.offerKey))
      .toEqual(['BUNNY:FR:TVOD', 'BUNNY:FR:EST', 'SINTEL:FR:TVOD', 'SINTEL:FR:EST']);
    const randomized = createDemoPlan({
      scenario: 'rental', count: 1, paceMs: 0, customerMode: 'random', customerCount: 1,
    }, { ...variedReferences, customers: references.customers }, 'random-film');
    expect(random).toHaveBeenCalledOnce();
    expect(randomized.transactions[0].offerKey).toBe('SINTEL:FR:TVOD');
  });

  it('reuses the only eligible film and permits a single mixed journey with just a rental offer', () => {
    const plan = createDemoPlan({
      scenario: 'mixed', count: 3, paceMs: 0, customerMode: 'random', customerCount: 1,
    }, references, 'single-film');
    expect(plan.transactions.map(row => row.contentKey)).toEqual(['SINTEL', 'SINTEL', 'SINTEL']);
    expect(createDemoPlan({
      scenario: 'mixed', count: 1, paceMs: 0, customerMode: 'random', customerCount: 1,
    }, { ...references, offers: [references.offers[0]] }, 'single-rental').transactions[0].transactionType).toBe('TVOD');
  });

  it('freezes random customer and film parameters across a lost order response and reference changes', async () => {
    const random = vi.spyOn(Math, 'random').mockReturnValue(0);
    const mutable = {
      customers: variedReferences.customers.map(row => ({ ...row })),
      offers: variedReferences.offers.map(row => ({ ...row })),
      content: variedReferences.content.map(row => ({ ...row })),
    };
    const plan = createDemoPlan({
      scenario: 'mixed', count: 3, paceMs: 0, customerMode: 'random', customerCount: 2,
    }, mutable, 'random-retry');
    const plannedInputs = plan.transactions.map((row, index) => ({ input: {
      customer_key: row.customerKey, offer_key: row.offerKey, idempotency_key: `demo:random-retry:${index}:order`,
    } }));
    const draws = random.mock.calls.length;
    const functions = boundary();
    vi.mocked(functions.placeOrder.invoke).mockRejectedValueOnce(new Error('Response lost after order commit.'));
    const run = new DemoScenario(plan, functions);
    expect((await run.execute()).status).toBe('failed');
    mutable.customers.forEach(row => { row.customer_key = 'changed'; row.territory = 'DE'; });
    mutable.offers.forEach(row => { row.offer_key = 'changed'; row.content_key = 'BROKEN'; });
    mutable.content.forEach(row => { row.duration_seconds = 1; });
    random.mockReturnValue(0.99);
    expect(await run.execute()).toMatchObject({ status: 'completed', completedTransactions: 3 });
    expect(vi.mocked(functions.placeOrder.invoke).mock.calls.map(([request]) => request))
      .toEqual([plannedInputs[0], ...plannedInputs]);
    expect(vi.mocked(functions.recordProgress.invoke).mock.calls.map(([request]) => request.input.position_seconds))
      .toEqual(plan.transactions.map(row => row.progressSeconds));
    expect(random).toHaveBeenCalledTimes(draws);
    expect(Object.isFrozen(plan)).toBe(true);
    expect(Object.isFrozen(plan.transactions)).toBe(true);
    expect(plan.transactions.every(Object.isFrozen)).toBe(true);
  });

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
      [{ input: { order_id: 'actual-order', idempotency_key: 'demo:retry-a:0:play' } }, { timeoutMs: 60_000 }],
      [{ input: { order_id: 'actual-order', idempotency_key: 'demo:retry-a:0:play' } }, { timeoutMs: 60_000 }],
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

  it.each([
    new Error('Request timed out after 60000ms'),
    Object.assign(new Error('Request timed out after 60000ms'), { name: 'FunctionsError' }),
    Object.assign(new Error('Request timed out after 60000ms'), { name: 'SdkError', code: 'UNAUTHORIZED' }),
    Object.assign(new Error('Operator permission expired or revoked.'), { name: 'SdkError' }),
    Object.assign(new Error('fetch failed'), { name: 'NetworkError' }),
  ])('does not automatically retry non-timeout SDK, authorization or business errors: %s', async error => {
    const functions = boundary();
    vi.mocked(functions.placeOrder.invoke).mockRejectedValue(error);
    const run = new DemoScenario(createDemoPlan({
      scenario: 'rental', count: 1, paceMs: 0, customerKey: 'MSF-C0001',
    }, references, 'no-retry'), functions);
    expect(await run.execute()).toMatchObject({ status: 'failed', error: error.message, receipts: [] });
    expect(functions.placeOrder.invoke).toHaveBeenCalledOnce();
    expect(functions.startPlayback.invoke).not.toHaveBeenCalled();
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
    expect(functions.placeOrder.invoke).toHaveBeenCalledOnce();
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
    } }, { timeoutMs: 60_000 });
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
    expect(functions.capabilities.invoke).toHaveBeenCalledWith(undefined, { timeoutMs: 60_000 });
    expect(functions.placeOrder.invoke).toHaveBeenCalledWith({ input: {
      customer_key: 'MSF-C0001', offer_key: 'SINTEL:FR:RENTAL', idempotency_key: 'demo:demo-a:0:order',
    } }, { timeoutMs: 60_000 });
    expect(functions.startPlayback.invoke).toHaveBeenCalledWith({ input: {
      order_id: 'actual-order', idempotency_key: 'demo:demo-a:0:play',
    } }, { timeoutMs: 60_000 });
    expect(functions.recordProgress.invoke).toHaveBeenCalledWith({ input: {
      session_id: 'actual-session', position_seconds: 60, idempotency_key: 'demo:demo-a:0:progress',
    } }, { timeoutMs: 60_000 });
  });
});
