import{afterEach,describe,expect,it,vi}from'vitest';
import{readOntologyGraph}from'../../apps/cockpit/rayfin/functions/src/ontology-graph';
const config={workspace_id:'d9c835a9-16d2-4997-9969-16cc4389a7c7',ontology_id:'3534d696-e727-45b3-9387-bbd155a82a52',
  graph_model_id:'1f368a35-95da-42a2-924d-ef4bb6bc9413',gold_item_id:'7eb1318d-e4b5-4bc4-ae12-6c3a46b1b7f5'};
const definition=(database:string)=>({definition:{parts:[
  {path:'expressions.tmdl',payload:Buffer.from(`Sql.Database("actual-endpoint","${database}")`).toString('base64')},
  {path:'entities/customer.tmdl',payload:Buffer.from('entity customer').toString('base64')},
  {path:'entityRelationships.tmdl',payload:Buffer.from('entityRelationship customer_order').toString('base64')},
]}});
afterEach(()=>vi.unstubAllGlobals());
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
    const binding={...config,id:'6396df52-7a4c-4a2c-91f5-49324f6f784f',
      binding_key:'business-ontology-v2',verified:true};
    vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(definition(config.gold_item_id)),{status:200}))
      .mockResolvedValueOnce(new Response(JSON.stringify({status:{code:'00000'},result:{data:[{
        customer_key:'customer-1',customer_name:'Fixture',order_id:'order-1',offer_key:'offer-1',
        content_key:'film-1',title:'Fixture film',
      }]}}),{status:200})));
    const result=await readOntologyGraph(binding,'test-only-token');
    expect(result.state).toBe('ready');expect(result.nodes).toHaveLength(4);expect(result.edges).toHaveLength(3);
    expect(result.source).toEqual(config);
  });
});
