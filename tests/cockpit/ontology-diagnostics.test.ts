import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

let readOntologyGraph: typeof import('../../apps/cockpit/rayfin/functions/src/ontology-graph')['readOntologyGraph'];
const config = {
  workspace_id: '33333333-3333-4333-8333-333333333333', ontology_id: '88888888-8888-4888-8888-888888888888',
  graph_model_id: '66666666-6666-4666-8666-666666666666', gold_item_id: '55555555-5555-4555-8555-555555555555', verified: true,
};
const token = 'private-access-token';
const order = {
  customer_key: 'private-customer-key', customer_name: 'Private customer name', order_id: 'private-order-id',
  created_at: '2026-10-10T12:00:00.000Z', order_status: 'active', amount_minor: 399, currency: 'EUR',
  offer_key: 'private-offer-key', content_key: 'private-film-key', title: 'Private film title',
};
const page = (data: unknown[], nextPage?: string) => new Response(JSON.stringify({
  status: { code: data.length ? '00000' : '02000' }, result: { data, nextPage },
}), { status: 200 });
type Event = Record<string, unknown>;
const events = (): Event[] => vi.mocked(console.log).mock.calls.map(([line]) => JSON.parse(line as string) as Event);
const event = (phase: string, status: string) => events().find(row => row.phase === phase && row.status === status);
const fetchGraph = (distributors: () => Promise<Response> = async () => page([])) => vi.fn(async (_url: string, init: RequestInit) => {
  const query = JSON.parse(init.body as string).query as string;
  if (query.includes('r.created_at')) return page([order]);
  return query.includes('content_distributor') ? distributors() : page([]);
});

beforeEach(async () => {
  vi.resetModules();
  vi.useFakeTimers();
  vi.setSystemTime(0);
  vi.spyOn(performance, 'now').mockImplementation(() => Date.now());
  vi.spyOn(console, 'log').mockImplementation(() => {});
  ({ readOntologyGraph } = await import('../../apps/cockpit/rayfin/functions/src/ontology-graph'));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });

describe('redacted graph boundary diagnostics', () => {
  it('measures headers, body and unchanged continuation waits under one read ID', async () => {
    let requests = 0;
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
      if (!(JSON.parse(init.body as string).query as string).includes('r.created_at')) return page([]);
      vi.setSystemTime(Date.now() + 120);
      const response = page([order], requests++ === 0 ? 'private-continuation/+1' : undefined);
      const json = response.json.bind(response);
      vi.spyOn(response, 'json').mockImplementation(async () => {
        vi.setSystemTime(Date.now() + 30);
        return json();
      });
      return response;
    }));
    const pending = readOntologyGraph(config, token);
    await vi.runAllTimersAsync();
    const result = await pending;
    expect(result.state).toBe('ready');
    expect(result.nodes).toHaveLength(4);
    expect(event('metadata', 'complete')).toMatchObject({ mode: 'verified' });
    expect(event('orders', 'headers')).toMatchObject({ http_status: 200, headers_ms: 120 });
    expect(event('orders', 'response')).toMatchObject({ graph_status: '00000', body_ms: 30, has_next_page: true });
    expect(event('orders', 'wait')).toMatchObject({ delay_ms: 2000 });
    expect(event('orders', 'complete')).toMatchObject({ request_count: 2, continuation_count: 1, row_count: 1, wait_ms: 2000, phase_ms: 2300 });
    expect(event('distributors', 'complete')).toMatchObject({ request_count: 1, row_count: 0 });
    expect(event('playback', 'complete')).toMatchObject({ request_count: 1, row_count: 0 });
    expect(event('assemble_orders', 'complete')).toMatchObject({ node_count: 4, edge_count: 3 });
    expect(event('assemble_context', 'complete')).toMatchObject({ node_count: 4, edge_count: 3 });
    expect(event('read', 'complete')).toMatchObject({ state: 'ready', elapsed_ms: 2300, node_count: 4, edge_count: 3 });
    const ids = new Set(events().map(row => row.read_id));
    expect(ids.size).toBe(1);
    expect([...ids][0]).toMatch(/^[a-f0-9-]{36}$/);
    const serialized = JSON.stringify(events());
    for (const sensitive of [token, ...Object.values(config).filter(value => typeof value === 'string'), order.customer_key,
      order.customer_name, order.order_id, order.title, 'private-continuation', 'MATCH ', 'https://', 'Authorization']) {
      expect(serialized).not.toContain(sensitive);
    }
  });

  it.each([
    ['request', async () => { throw new DOMException('private-token https://private-host/query', 'TimeoutError'); }, undefined, 'timeout'],
    ['body', async () => new Response('Private customer name is not JSON', { status: 200 }), 200, 'invalid_json'],
    ['status', async () => new Response(JSON.stringify({ errorCode: 'Private customer name' }), { status: 500 }), 500, 'error'],
    ['status', async () => new Response(JSON.stringify({ status: { code: 'private-token https://private-host/query' } }), { status: 200 }), 200, 'error'],
    ['rows', async () => page([null]), 200, 'error'],
  ] as const)('attributes %s failures to the correct parallel context branch without logging content', async (stage, fail, httpStatus, kind) => {
    vi.stubGlobal('fetch', fetchGraph(fail));
    await expect(readOntologyGraph(config, token)).rejects.toThrow();
    expect(event('distributors', 'failed')).toMatchObject({ failure_stage: stage, error_kind: kind, request_count: 1 });
    expect(event('distributors', 'failed')?.http_status).toBe(httpStatus);
    expect(event('read', 'failed')).toBeDefined();
    expect(event('read', 'complete')).toBeUndefined();
    const serialized = JSON.stringify(events());
    for (const sensitive of [token, 'Private customer name', 'private-token', 'https://', 'private-host']) {
      expect(serialized).not.toContain(sensitive);
    }
  });

  it('records the eight-request bound as pending rather than completed rows', async () => {
    const fetch = vi.fn(async () => page([order], 'private-continuation'));
    vi.stubGlobal('fetch', fetch);
    const pending = readOntologyGraph(config, token);
    await vi.runAllTimersAsync();
    expect((await pending).state).toBe('pending');
    expect(fetch).toHaveBeenCalledTimes(8);
    expect(event('orders', 'pending')).toMatchObject({ reason: 'continuation_limit', request_count: 8, continuation_count: 8, row_count: 1, wait_ms: 14000 });
    expect(event('read', 'complete')).toMatchObject({ state: 'pending', node_count: 0, edge_count: 0 });
    expect(event('orders', 'complete')).toBeUndefined();
  });

  it('distinguishes shared-budget exhaustion from GraphNotQueryable', async () => {
    const fetch = vi.fn(async () => { vi.setSystemTime(45000); return page([order]); });
    vi.stubGlobal('fetch', fetch);
    expect((await readOntologyGraph(config, token)).state).toBe('pending');
    expect(fetch).toHaveBeenCalledOnce();
    expect(event('distributors', 'pending')).toMatchObject({ reason: 'deadline', request_count: 0 });
    expect(event('playback', 'pending')).toMatchObject({ reason: 'deadline', request_count: 0 });
    vi.mocked(console.log).mockClear();
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ errorCode: 'GraphNotQueryable' }), { status: 400 })));
    expect((await readOntologyGraph(config, token)).state).toBe('pending');
    expect(event('orders', 'pending')).toMatchObject({ reason: 'not_queryable', http_status: 400, request_count: 1 });
  });

  it('attributes metadata and assembly errors outside the query loop', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 503 })));
    await expect(readOntologyGraph({ ...config, verified: false }, token)).rejects.toThrow('503');
    expect(event('metadata', 'failed')).toBeDefined();
    vi.mocked(console.log).mockClear();
    vi.stubGlobal('fetch', vi.fn(async () => page([{ ...order, customer_key: 'private invalid key' }])));
    await expect(readOntologyGraph(config, token)).rejects.toThrow('invalid business key');
    expect(event('assemble_orders', 'failed')).toBeDefined();
    expect(JSON.stringify(events())).not.toContain('private invalid key');
  });

  it('does not let a logging failure change results or replace the original exception', async () => {
    vi.mocked(console.log).mockImplementation(() => { throw new Error('logging unavailable'); });
    vi.stubGlobal('fetch', fetchGraph());
    expect((await readOntologyGraph(config, token)).state).toBe('ready');
    const original = new Error('upstream failure');
    vi.stubGlobal('fetch', vi.fn(async () => { throw original; }));
    await expect(readOntologyGraph(config, token)).rejects.toBe(original);
  });

  it('keeps concurrent reads separately correlated', async () => {
    vi.stubGlobal('fetch', fetchGraph());
    await Promise.all([readOntologyGraph(config, token), readOntologyGraph(config, token)]);
    const ids = new Set(events().filter(row => row.phase === 'read' && row.status === 'start').map(row => row.read_id));
    expect(ids.size).toBe(2);
    for (const id of ids) {
      expect(events().filter(row => row.read_id === id && row.phase === 'read' && row.status === 'complete')).toHaveLength(1);
    }
  });
});
