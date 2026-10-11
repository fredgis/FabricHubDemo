// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RayfinClient } from '@microsoft/rayfin-client';
import type { AppSchema } from '../../rayfin/data/schema';
import type { AppFunctionsSchema } from '../../rayfin/functions/src/types';
import { createDemoPlan, DemoScenario, type DemoFunctions } from '../domain/demo-scenario';

type FunctionName = keyof DemoFunctions;
type Request = { name: FunctionName; input: Record<string, string | number>; sentAt: number };
const clients: RayfinClient<AppSchema, AppFunctionsSchema>[] = [];
const references = {
  customers: [{ customer_key: 'TEST-CUSTOMER', territory: 'FR' }],
  content: [{ content_key: 'TEST-FILM', duration_seconds: 90 }],
  offers: [{ offer_key: 'TEST-OFFER', content_key: 'TEST-FILM', territory: 'FR', transaction_type: 'TVOD' }],
};

const functionNames = ['capabilities', 'placeOrder', 'startPlayback', 'recordProgress'] as const;

function transport(dropFor: FunctionName, drops = 1) {
  const calls: Request[] = [];
  const committed = new Map<string, { input: Request['input']; output: unknown }>();
  const fetch: typeof globalThis.fetch = async (url, options) => {
    const name = /\/functions\/([^/]+)\/invoke$/.exec(String(url))?.[1] as FunctionName;
    if (!functionNames.includes(name)) throw new Error(`Unexpected test request: ${String(url)}`);
    const input = JSON.parse(String(options?.body)).input ?? {};
    calls.push({ name, input, sentAt: Date.now() });
    let output: unknown = { can_operate: true, reason: 'Test operator' };
    if (name !== 'capabilities') {
      const key = String(input.idempotency_key);
      const previous = committed.get(key);
      if (previous) {
        expect(input).toEqual(previous.input);
        output = previous.output;
      } else {
        output = {
          entity_key: name === 'recordProgress' ? input.session_id : `${name}:${key}`,
          status: name === 'placeOrder' ? 'booked' : 'playing',
          event_ids: name === 'startPlayback' ? [`${key}:activated`, `${key}:started`] : [`${key}:event`],
        };
        committed.set(key, { input, output });
      }
    }
    if (name === dropFor && drops > 0) {
      drops--;
      return new Promise<Response>((_resolve, reject) => {
        const signal = options?.signal;
        if (signal?.aborted) reject(signal.reason);
        else signal?.addEventListener('abort', () => reject(signal.reason), { once: true });
      });
    }
    return new Response(JSON.stringify({ status: 'success', output }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    });
  };
  vi.stubGlobal('fetch', fetch);
  const client = new RayfinClient<AppSchema, AppFunctionsSchema>({
    baseUrl: 'https://demo-test.invalid', publishableKey: 'pk-test-only', authStorage: false,
    autoRefreshToken: false, multiTabSync: false,
  });
  clients.push(client);
  return { client, calls, committed, recover: () => { drops = 0; } };
}

function scenario(functions: DemoFunctions) {
  return new DemoScenario(createDemoPlan({
    scenario: 'rental', customerKey: 'TEST-CUSTOMER', count: 1, paceMs: 0,
  }, references, 'timeout-recovery'), functions);
}

afterEach(() => {
  clients.splice(0).forEach(client => client.auth.destroy());
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('Demo recovery through the installed Rayfin HTTP client', () => {
  it('reproduces the reported SDK timeout when a response never arrives', async () => {
    vi.useFakeTimers();
    const { client } = transport('capabilities');
    const request = client.functions.capabilities.invoke().catch(error => error);
    await vi.advanceTimersByTimeAsync(250_000);
    expect(await request).toMatchObject({ name: 'SdkError', message: 'Request timed out after 250000ms' });
  });

  it.each(functionNames)(
    'recovers one missing %s response without another user click or duplicate command', async name => {
      vi.useFakeTimers();
      const { client, calls, committed } = transport(name);
      const run = scenario(client.functions);
      const executing = run.execute();
      const prefix = functionNames.slice(0, functionNames.indexOf(name) + 1);
      await vi.advanceTimersByTimeAsync(59_999);
      expect(calls.map(call => call.name)).toEqual(prefix);
      expect(run.state).toMatchObject({ status: 'running', error: '' });
      expect(run.state.receipts).toHaveLength(Math.max(0, prefix.length - 2));
      await vi.advanceTimersByTimeAsync(2_000);
      expect(calls.map(call => call.name)).toEqual(prefix);
      await vi.advanceTimersByTimeAsync(1);
      const state = await executing;
      expect(state, state.error).toMatchObject({ status: 'completed', completedTransactions: 1, error: '' });
      expect(state.receipts).toHaveLength(3);
      expect(committed.size).toBe(3);
      const retried = calls.filter(call => call.name === name);
      expect(retried).toHaveLength(2);
      expect(retried[1].input).toEqual(retried[0].input);
      expect(retried[1].sentAt - retried[0].sentAt).toBe(62_000);
      for (const other of functionNames) {
        if (other !== name) expect(calls.filter(call => call.name === other)).toHaveLength(1);
      }
    },
  );

  it.each(functionNames)('bounds repeated %s timeouts and keeps manual recovery on the same run', async name => {
    vi.useFakeTimers();
    const { client, calls, committed, recover } = transport(name, Infinity);
    const run = scenario(client.functions);
    const executing = run.execute();
    await vi.advanceTimersByTimeAsync(187_000);
    expect(await executing).toMatchObject({
      status: 'failed', error: `${name} did not respond after 3 attempts. Its result is unconfirmed.`,
    });
    const retried = calls.filter(call => call.name === name);
    expect(retried).toHaveLength(3);
    expect(retried.map(call => call.sentAt - retried[0].sentAt)).toEqual([0, 62_000, 127_000]);
    expect(retried.every(call => JSON.stringify(call.input) === JSON.stringify(retried[0].input))).toBe(true);
    expect(calls.map(call => call.name)).toEqual([
      ...functionNames.slice(0, functionNames.indexOf(name)), name, name, name,
    ]);
    await vi.advanceTimersByTimeAsync(250_000);
    expect(calls.filter(call => call.name === name)).toHaveLength(3);

    const confirmed = run.state.receipts;
    recover();
    const resumed = await run.execute();
    expect(resumed).toMatchObject({ status: 'completed', completedTransactions: 1, error: '' });
    expect(resumed.receipts).toHaveLength(3);
    expect(resumed.receipts.slice(0, confirmed.length)).toEqual(confirmed);
    expect(committed.size).toBe(3);
    expect(calls.filter(call => call.name === name)).toHaveLength(4);
    for (const receipt of confirmed) expect(calls.filter(call => call.name === receipt.command)).toHaveLength(1);
  });

  it.each([30_000, 60_001])('cancels at %ims without retrying or losing an unconfirmed command', async elapsed => {
    vi.useFakeTimers();
    const { client, calls, committed } = transport('startPlayback');
    const run = scenario(client.functions);
    const executing = run.execute();
    await vi.advanceTimersByTimeAsync(elapsed);
    run.cancel();
    await vi.runAllTimersAsync();
    expect(await executing).toMatchObject({ status: 'failed', cancelRequested: true });
    expect(run.state.receipts).toHaveLength(1);
    expect(calls.map(call => call.name)).toEqual(['capabilities', 'placeOrder', 'startPlayback']);
    expect(committed.size).toBe(2);

    expect(await run.execute()).toMatchObject({ status: 'completed', cancelRequested: false });
    expect(committed.size).toBe(3);
    expect(calls.filter(call => call.name === 'placeOrder')).toHaveLength(1);
    expect(calls.filter(call => call.name === 'startPlayback')).toHaveLength(2);
  });

  it('shares an execution while waiting to retry instead of starting parallel commands', async () => {
    vi.useFakeTimers();
    const { client, calls } = transport('placeOrder');
    const run = scenario(client.functions);
    const executing = run.execute();
    await vi.advanceTimersByTimeAsync(60_001);
    expect(run.execute()).toBe(executing);
    await vi.runAllTimersAsync();
    expect(await executing).toMatchObject({ status: 'completed', completedTransactions: 1 });
    expect(calls.map(call => call.name)).toEqual([
      'capabilities', 'placeOrder', 'placeOrder', 'startPlayback', 'recordProgress',
    ]);
  });

  it('finishes 100 mixed random-customer journeys after response loss without rerolling or duplicates', async () => {
    vi.useFakeTimers();
    vi.spyOn(Math, 'random').mockReturnValue(0.25);
    const { client, calls, committed } = transport('startPlayback');
    const plan = createDemoPlan({
      scenario: 'mixed', customerMode: 'random', customerCount: 100, count: 100, paceMs: 250,
    }, {
      ...references,
      customers: Array.from({ length: 100 }, (_, i) => ({ customer_key: `TEST-CUSTOMER-${i}`, territory: 'FR' })),
      offers: [...references.offers, { ...references.offers[0], offer_key: 'TEST-PURCHASE', transaction_type: 'EST' }],
    }, 'hundred-journeys');
    const original = structuredClone(plan);
    const executing = new DemoScenario(plan, client.functions).execute();
    await vi.runAllTimersAsync();
    const state = await executing;
    expect(state, state.error).toMatchObject({ status: 'completed', completedTransactions: 100, error: '' });
    expect(plan).toEqual(original);
    expect(state.receipts).toHaveLength(300);
    expect(committed.size).toBe(300);
    expect(calls).toHaveLength(302);
    expect(new Set(state.receipts.flatMap(receipt => receipt.result.event_ids)).size).toBe(400);
    expect(calls.filter(call => call.name === 'placeOrder').map(call => call.input)).toEqual(
      original.transactions.map((row, index) => ({ customer_key: row.customerKey, offer_key: row.offerKey,
        idempotency_key: `demo:hundred-journeys:${index}:order` })),
    );
    for (let i = 0; i < 100; i++) {
      const playback = calls.find(call => call.input.idempotency_key === `demo:hundred-journeys:${i}:play`);
      const progress = calls.find(call => call.input.idempotency_key === `demo:hundred-journeys:${i}:progress`);
      expect(playback?.input.order_id).toBe(state.receipts[i * 3].result.entity_key);
      expect(progress?.input.session_id).toBe(state.receipts[i * 3 + 1].result.entity_key);
    }
  });
});
