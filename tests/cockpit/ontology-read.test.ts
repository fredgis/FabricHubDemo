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
afterEach(()=>{vi.unstubAllGlobals();vi.restoreAllMocks();});
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
    const fetch=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({status:{code:'00000'},result:{data:[{
        customer_key:'customer-1',customer_name:'Fixture',order_id:'order-1',offer_key:'offer-1',
        content_key:'film-1',title:'Fixture film',
      }]}}),{status:200}));
    vi.stubGlobal('fetch',fetch);
    const result=await readOntologyGraph(binding,'test-only-token');
    expect(result.state).toBe('ready');expect(result.nodes).toHaveLength(4);expect(result.edges).toHaveLength(3);
    expect(result.source).toEqual(config);
    expect(fetch).toHaveBeenCalledOnce();
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
});
