import{afterEach,beforeEach,describe,expect,it,vi}from'vitest';
let readOntologyGraph:typeof import('../../apps/cockpit/rayfin/functions/src/ontology-graph')['readOntologyGraph'];
beforeEach(async()=>{
  vi.resetModules();
  ({readOntologyGraph}=await import('../../apps/cockpit/rayfin/functions/src/ontology-graph'));
});
const config={workspace_id:'33333333-3333-4333-8333-333333333333',ontology_id:'88888888-8888-4888-8888-888888888888',
  graph_model_id:'66666666-6666-4666-8666-666666666666',gold_item_id:'55555555-5555-4555-8555-555555555555'};
const definition=(database:string)=>({definition:{parts:[
  {path:'expressions.tmdl',payload:Buffer.from(`Sql.Database("actual-endpoint","${database}")`).toString('base64')},
  {path:'entities/customer.tmdl',payload:Buffer.from('entity customer').toString('base64')},
  {path:'entityRelationships.tmdl',payload:Buffer.from('entityRelationship customer_order').toString('base64')},
]}});
const orderRow = (id = 'order-1', created = '2026-10-10T12:00:00.000Z') => ({
  customer_key: 'customer-1', customer_name: 'Fixture customer', order_id: id,
  created_at: created, order_status: 'active', amount_minor: 399, currency: 'EUR',
  offer_key: 'offer-1', content_key: 'film-1', title: 'Fixture film',
});
const sessionRow = (id = 'session-1', order = 'order-1') => ({
  session_id: id, order_id: order, content_key: 'film-1', customer_key: 'customer-1',
  playback_order_id: order, playback_content_key: 'film-1', playback_status: 'playing', position_seconds: 30,
});
const response = (data: unknown[], nextPage?: string) => new Response(JSON.stringify({
  status: { code: data.length ? '00000' : '02000' }, result: { data, ...(nextPage ? { nextPage } : {}) },
}), { status: 200 });
const graphFetch = (orders: unknown[] = [orderRow()], sessions: unknown[] = [], distributors: unknown[] = []) => vi.fn(async (_url: string, options?: RequestInit) => {
  const query: string = JSON.parse(options!.body as string).query;
  return response(query.includes('r.created_at') ? orders : query.includes('content_distributor') ? distributors : sessions);
});
afterEach(()=>{vi.unstubAllGlobals();vi.restoreAllMocks();vi.useRealTimers();});
describe('actual ontology graph read boundary',()=>{
  it('rejects Silver bindings without drawing operational data as Gold ontology instances',async()=>{
    vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(definition('silver-item')),{status:200})));
    const result=await readOntologyGraph(config,'test-only-token');
    expect(result.state).toBe('binding-mismatch');expect(result.nodes).toEqual([]);expect(result.edges).toEqual([]);
  });
  it('preserves real graph initial-load failure as pending, not synthetic graph success',async()=>{
    vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(definition(config.gold_item_id)),{status:200}))
      .mockResolvedValueOnce(new Response(JSON.stringify({errorCode:'GraphNotQueryable'}),{status:400})));
    const result=await readOntologyGraph(config,'test-only-token');
    expect(result.state).toBe('pending');expect(result.nodes).toEqual([]);
  });
  it('accepts a persisted binding row with non-UUID metadata and returns only source coordinates',async()=>{
    const binding={...config,id:'99999999-9999-4999-8999-999999999999',
      binding_key:'business-ontology-v2',verified:true};
    const fetch=graphFetch();
    vi.stubGlobal('fetch',fetch);
    const result=await readOntologyGraph(binding,'test-only-token');
    expect(result.state).toBe('ready');expect(result.nodes).toHaveLength(4);expect(result.edges).toHaveLength(3);
    expect(result.source).toEqual(config);
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(fetch.mock.calls[0][0]).toContain('executeQuery');
  });
  it('reuses only qualified metadata while querying fresh graph data each time',async()=>{
    const fetch=vi.fn(async(url:string)=>new Response(JSON.stringify(url.includes('getDefinition')
      ?definition(config.gold_item_id):{status:{code:'00000'},result:{data:[]}}),{status:200}));
    vi.stubGlobal('fetch',fetch);
    await readOntologyGraph(config,'same-token');
    await readOntologyGraph(config,'same-token');
    expect(fetch.mock.calls.filter(([url])=>url.includes('getDefinition'))).toHaveLength(1);
    expect(fetch.mock.calls.filter(([url])=>url.includes('executeQuery'))).toHaveLength(2);
  });
  it('expires cached metadata and does not reuse it for another access token',async()=>{
    let now=1000;vi.spyOn(Date,'now').mockImplementation(()=>now);
    const fetch=vi.fn(async(url:string)=>new Response(JSON.stringify(url.includes('getDefinition')
      ?definition(config.gold_item_id):{status:{code:'00000'},result:{data:[]}}),{status:200}));
    vi.stubGlobal('fetch',fetch);
    await readOntologyGraph(config,'token-a');
    await readOntologyGraph(config,'token-b');
    now+=120001;
    await readOntologyGraph(config,'token-a');
    expect(fetch.mock.calls.filter(([url])=>url.includes('getDefinition'))).toHaveLength(3);
  });
  it('queries only the requested six journeys and rejects unbounded limits before a request',async()=>{
    const queries:string[]=[];
    const fetch=vi.fn(async(url:string,options?:RequestInit)=>{
      if(url.includes('executeQuery')&&typeof options?.body==='string')queries.push(JSON.parse(options.body).query);
      return new Response(JSON.stringify(url.includes('getDefinition')
        ?definition(config.gold_item_id):{status:{code:'00000'},result:{data:[]}}),{status:200});
    });
    vi.stubGlobal('fetch',fetch);
    const result=await readOntologyGraph(config,'slice-token',6);
    expect(result.limit).toBe(6);
    expect(queries).toEqual([expect.stringMatching(/LIMIT 6$/)]);
    await expect(readOntologyGraph(config,'slice-token',50000)).rejects.toThrow('limit');
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it.each([6, 12, 24, 50])('sorts on creation time and ID before the %i order limit', async limit => {
    const fetch = graphFetch(); vi.stubGlobal('fetch', fetch);
    const result = await readOntologyGraph({ ...config, verified: true }, 'test-token', limit);
    expect(result.limit).toBe(limit);
    const queries = fetch.mock.calls.map(([, init]) => JSON.parse(init!.body as string).query as string);
    expect(queries[0]).toMatch(new RegExp(`ORDER BY r.created_at DESC, r.order_id DESC\\s+LIMIT ${limit}$`));
    expect(queries[0]).not.toMatch(/playback|distributor/);
    expect(queries[1]).toContain("WHERE f.content_key IN ['film-1']");
    expect(queries[2]).toContain("WHERE r.order_id IN ['order-1']");
    expect(queries.slice(1).every(query => query.endsWith('LIMIT 201'))).toBe(true);
    expect(result.nodes.find(node => node.type === 'rental')).toMatchObject({
      created_at: '2026-10-10T12:00:00.000Z', status: 'active', amount_minor: 399, currency: 'EUR',
    });
    expect(fetch.mock.calls.every(([, init]) => (init!.headers as Record<string, string>)['x-ms-fabric-skill'] === 'fabriciq-ontology-cli')).toBe(true);
  });
  it('keeps orders with no published distributor or playback relationships', async () => {
    vi.stubGlobal('fetch', graphFetch());
    const result = await readOntologyGraph({ ...config, verified: true }, 'test-token');
    expect(result.limit).toBe(12);
    expect(result.nodes).toHaveLength(4); expect(result.edges).toHaveLength(3);
    expect(result.context).toEqual({ playback_limit: 200, playback_truncated: false, distributor_limit: 200, distributors_truncated: false });
  });
  it('reads both context branches in parallel and preserves only the actual edge directions', async () => {
    let release!: () => void;
    const barrier = new Promise<void>(resolve => { release = resolve; });
    const fetch = vi.fn(async (_url: string, options: RequestInit) => {
      const query = JSON.parse(options.body as string).query as string;
      if (query.includes('r.created_at')) return response([orderRow()]);
      if (query.includes('content_distributor')) {
        await barrier;
        return response([{ content_key: 'film-1', distributor_key: 'D1', distributor_name: 'Fixture distributor' }]);
      }
      release(); return response([sessionRow(), sessionRow('session-2')]);
    });
    vi.stubGlobal('fetch', fetch);
    const result = await readOntologyGraph({ ...config, verified: true }, 'test-token');
    expect(result.nodes).toHaveLength(7);
    expect(result.edges).toHaveLength(8);
    expect(result.edges).toContainEqual({ from: 'content:film-1', to: 'distributor:D1', type: 'content_distributor' });
    expect(result.edges).toContainEqual({ from: 'playback:session-1', to: 'rental:order-1', type: 'playback_order' });
    expect(result.edges).toContainEqual({ from: 'playback:session-1', to: 'content:film-1', type: 'playback_content' });
    expect(result.edges.some(edge => edge.type === 'playback_customer')).toBe(false);
    expect(result.nodes.find(node => node.key === 'playback:session-1')).toMatchObject({ status: 'playing', position_seconds: 30 });
  });
  it('retains all selected orders when context reaches its cap and reports truncation', async () => {
    const sessions = Array.from({ length: 201 }, (_, index) => sessionRow(`session-${index}`));
    const distributors = Array.from({ length: 201 }, (_, index) => ({ content_key: 'film-1', distributor_key: `D${index}`, distributor_name: `Fixture ${index}` }));
    vi.stubGlobal('fetch', graphFetch([orderRow()], sessions, distributors));
    const result = await readOntologyGraph({ ...config, verified: true }, 'test-token');
    expect(result.nodes.filter(node => node.type === 'rental')).toHaveLength(1);
    expect(result.nodes.filter(node => node.type === 'playback')).toHaveLength(200);
    expect(result.nodes.filter(node => node.type === 'distributor')).toHaveLength(200);
    expect(result.context).toMatchObject({ playback_truncated: true, distributors_truncated: true });
  });
  it('accumulates pages and deduplicates overlapping rows instead of discarding earlier pages', async () => {
    vi.useFakeTimers();
    const first = orderRow('order-2'); const second = orderRow('order-1', '2026-10-09T12:00:00.000Z');
    let page = 0;
    const fetch = vi.fn(async (_url: string, options: RequestInit) => {
      const query = JSON.parse(options.body as string).query as string;
      if (!query.includes('r.created_at')) return response([]);
      return page++ === 0 ? response([first], 'page/+1') : response([first, second]);
    });
    vi.stubGlobal('fetch', fetch);
    const pending = readOntologyGraph({ ...config, verified: true }, 'test-token');
    await vi.runAllTimersAsync(); const result = await pending;
    expect(result.nodes.filter(node => node.type === 'rental').map(node => node.label)).toEqual(['order-2', 'order-1']);
    expect(result.edges).toHaveLength(5);
    expect(fetch.mock.calls[1][0]).toContain('continuationToken=page%2F%2B1');
  });
  it('accumulates context pages as well as order pages', async () => {
    vi.useFakeTimers(); let page = 0;
    const fetch = vi.fn(async (_url: string, options: RequestInit) => {
      const query = JSON.parse(options.body as string).query as string;
      if (query.includes('r.created_at')) return response([orderRow()]);
      if (query.includes('content_distributor')) return response([]);
      return page++ === 0 ? response([sessionRow()], 'next') : response([sessionRow(), sessionRow('session-2')]);
    });
    vi.stubGlobal('fetch', fetch);
    const pending = readOntologyGraph({ ...config, verified: true }, 'test-token');
    await vi.runAllTimersAsync(); const result = await pending;
    expect(result.nodes.filter(node => node.type === 'playback')).toHaveLength(2);
    expect(result.edges.filter(edge => edge.type === 'playback_order')).toHaveLength(2);
  });
  it('does not present an unfinished bounded query as complete', async () => {
    vi.useFakeTimers();
    const fetch = vi.fn(async () => response([orderRow()], 'still-running')); vi.stubGlobal('fetch', fetch);
    const pending = readOntologyGraph({ ...config, verified: true }, 'test-token');
    await vi.runAllTimersAsync(); const result = await pending;
    expect(fetch).toHaveBeenCalledTimes(8);
    expect(result.state).toBe('pending'); expect(result.nodes).toEqual([]);
  });
  it('shares the remaining time budget across the main read and both context branches', async () => {
    let now = 1000; vi.spyOn(Date, 'now').mockImplementation(() => now);
    const timeout = vi.spyOn(AbortSignal, 'timeout');
    vi.stubGlobal('fetch', vi.fn(async (_url: string, options: RequestInit) => {
      if (JSON.parse(options.body as string).query.includes('r.created_at')) {
        now += 20000; return response([orderRow()]);
      }
      return response([]);
    }));
    expect((await readOntologyGraph({ ...config, verified: true }, 'test-token')).state).toBe('ready');
    expect(timeout.mock.calls.map(([ms]) => ms)).toEqual([30000, 25000, 25000]);
  });
  it('does not start context reads after the common 45-second budget is exhausted', async () => {
    let now = 1000; vi.spyOn(Date, 'now').mockImplementation(() => now);
    const fetch = vi.fn(async () => { now += 45000; return response([orderRow()]); });
    vi.stubGlobal('fetch', fetch);
    const result = await readOntologyGraph({ ...config, verified: true }, 'test-token');
    expect(result.state).toBe('pending'); expect(result.nodes).toEqual([]);
    expect(fetch).toHaveBeenCalledOnce();
  });
  it.each([
    { content_key: "film-1'] MATCH (n) RETURN n //" }, { order_id: 'order\n1' }, { customer_key: 7 },
    { created_at: 'not-a-date' }, { amount_minor: Number.MAX_SAFE_INTEGER + 1 }, { currency: 'invalid' },
  ])('rejects malformed source properties before context queries: %j', async patch => {
    const fetch = graphFetch([{ ...orderRow(), ...patch }]); vi.stubGlobal('fetch', fetch);
    await expect(readOntologyGraph({ ...config, verified: true }, 'test-token')).rejects.toThrow('invalid');
    expect(fetch).toHaveBeenCalledOnce();
  });
  it.each([
    { order_id: 'unselected-order' }, { content_key: 'another-film' }, { customer_key: 'another-customer' },
    { playback_order_id: 'another-order' }, { playback_content_key: 'another-film' },
  ])('rejects a playback not belonging to its selected path: %j', async patch => {
    vi.stubGlobal('fetch', graphFetch([orderRow()], [{ ...sessionRow(), ...patch }]));
    await expect(readOntologyGraph({ ...config, verified: true }, 'test-token')).rejects.toThrow('does not match');
  });
  it('rejects distributors outside the selected films', async () => {
    vi.stubGlobal('fetch', graphFetch([orderRow()], [], [{ content_key: 'other-film', distributor_key: 'D1', distributor_name: 'Fixture' }]));
    await expect(readOntologyGraph({ ...config, verified: true }, 'test-token')).rejects.toThrow('outside');
  });
  it('preserves pending during a GraphModel refresh between the order and context reads', async () => {
    vi.stubGlobal('fetch', vi.fn(async (_url: string, options: RequestInit) => JSON.parse(options.body as string).query.includes('r.created_at')
      ? response([orderRow()]) : new Response(JSON.stringify({ errorCode: 'GraphNotQueryable' }), { status: 400 })));
    const result = await readOntologyGraph({ ...config, verified: true }, 'test-token');
    expect(result.state).toBe('pending'); expect(result.nodes).toEqual([]);
  });
  it('does not silently ignore a failed context query', async () => {
    vi.stubGlobal('fetch', vi.fn(async (_url: string, options: RequestInit) => JSON.parse(options.body as string).query.includes('r.created_at')
      ? response([orderRow()]) : new Response(JSON.stringify({ status: { code: '42000' } }), { status: 200 })));
    await expect(readOntologyGraph({ ...config, verified: true }, 'test-token')).rejects.toThrow('42000');
  });
});
