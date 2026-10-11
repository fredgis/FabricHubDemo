import { AudienceType, UserDataFunctions, type RayfinContext } from '@microsoft/fabric-user-data-functions';
import type { AppSchema, OperatorGrant, RuntimeBinding } from '../../data/schema.js';
import { assertOperator, epoch, type Capabilities, type CommandResult, type ControlInput, type Health,
  type OrderInput, type PlayInput, type ProgressInput } from './domain.js';
import { atomic, poolFor, type Store } from './storage.js';
import { withOperationalPool } from './operational-connection.js';
import { assertOrdersPage, readOperationalOrders, type OperationalOrdersPage } from './operational-orders.js';
import * as commands from './commands.js';
import {readGoldDashboard,type GoldDashboard} from './gold-dashboard.js';
import{goldView,readGoldPages,type GoldPages}from'./gold-pages.js';
import { readGoldInsights } from './gold-insights.js';
import type { GoldInsights } from './gold-insights-contract.js';
import { readCampaignImpact } from './gold-campaign-impact.js';
import type { CampaignImpact } from './gold-campaign-contract.js';
import{readOntologyGraph,type OntologyGraph}from'./ontology-graph.js';
import { askNativeFlixy, assertFlixyIdentity, flixyAgentId, type FlixyAnswer } from './flixy.js';

const udf = new UserDataFunctions();
async function operator(ctx: RayfinContext<AppSchema>): Promise<OperatorGrant> {
  const grants = await ctx.getDataClient().OperatorGrant.select(['id','user_id','enabled','expires_at']).execute();
  const grant = grants.find(g => g.enabled && epoch(g.expires_at) > Date.now());
  assertOperator(grant, new Date());
  return grant as OperatorGrant;
}
async function binding(ctx: RayfinContext<AppSchema>): Promise<RuntimeBinding> {
  const bindings = await ctx.getDataClient().RuntimeBinding.select(['id','binding_key','sql_server',
    'sql_database','fabric_item_id','workspace_id','capacity_id','verified'])
    .where({ binding_key: { eq: 'app-linked-operational' } }).execute();
  if (bindings.length !== 1 || !bindings[0].verified)
    throw new Error('Operational SQL is not bound. An administrator must validate the app-linked database.');
  return bindings[0];
}
async function run(ctx: RayfinContext<AppSchema, AudienceType.Sql>, id: string, name: string,
  params: unknown, work: (store: Store) => Promise<CommandResult>): Promise<CommandResult> {
  const grant = await operator(ctx);
  const pool = await poolFor(await binding(ctx), ctx.Tokens.Sql);
  try { return await atomic(pool, grant, id, name, params, work); }
  finally { await pool.close(); }
}
udf.func('capabilities', async (ctx: RayfinContext<AppSchema>): Promise<Capabilities> => {
  const grants = await ctx.getDataClient().OperatorGrant.select(['enabled','expires_at']).execute();
  const allowed = grants.some(g => g.enabled && epoch(g.expires_at) > Date.now());
  return { can_operate: allowed, reason: allowed ? 'Time-bounded operator grant' : 'Read-only viewer. Ask an administrator for an operator grant.' };
}, []);
udf.func('health', async (ctx: RayfinContext<AppSchema, AudienceType.Sql>): Promise<Health> => {
  return withOperationalPool(await binding(ctx), ctx.Tokens.Sql, async pool => {
    const count = await pool.request().query('SELECT COUNT(*) AS pending FROM dbo.Outboxes WHERE published_at IS NULL');
    return { database: 'App-linked SQL and expected tables verified', functions: 'Native UDF invocation verified',
      outbox_pending: count.recordset[0].pending, broker: 'Delivery is acknowledged by the external producer, not by this app.' };
  });
}, []);
udf.func('operationalOrders', async (ordersPage: number, playbackPage: number,
  ctx: RayfinContext<AppSchema, AudienceType.Sql>): Promise<OperationalOrdersPage> => {
  assertOrdersPage(ordersPage, 'ordersPage');
  assertOrdersPage(playbackPage, 'playbackPage');
  // Rental/Playback expose all rows to authenticated readers, with no field exclusions or row policy.
  // Keep the binding lookup caller-scoped; SQL tokens represent the app identity, not the viewer.
  return readOperationalOrders(await binding(ctx), ctx.Tokens.Sql, ordersPage, playbackPage);
}, []);
async function analytics(ctx:RayfinContext<AppSchema>){
  const[operational,configured]=await Promise.all([binding(ctx),ctx.getDataClient().AnalyticsBinding.select(['id','binding_key','name','sql_server',
    'sql_database','item_id','workspace_id','capacity_id','verified'])
    .where({binding_key:{eq:'business-gold'}}).execute()]);
  if(configured.length!==1 || configured[0].workspace_id!==operational.workspace_id ||
    configured[0].capacity_id!==operational.capacity_id)
    throw new Error('Verified Gold binding in the app workspace is missing. No operational fallback.');
  return configured[0];
}
udf.func('businessDashboard',async(ctx:RayfinContext<AppSchema,AudienceType.Sql>):Promise<GoldDashboard>=>{
  return readGoldDashboard(await analytics(ctx),ctx.Tokens.Sql);
},[]);
udf.func('businessViews',async(ctx:RayfinContext<AppSchema,AudienceType.Sql>):Promise<GoldPages>=>{
  return readGoldPages(await analytics(ctx),ctx.Tokens.Sql);
},[]);
udf.func('businessInsights', async (filtersJson: string,
  ctx: RayfinContext<AppSchema, AudienceType.Sql>): Promise<GoldInsights> => {
  return readGoldInsights(await analytics(ctx), ctx.Tokens.Sql, filtersJson);
}, []);
udf.func('getCampaignImpact', async (filtersJson: string,
  ctx: RayfinContext<AppSchema, AudienceType.Sql>): Promise<CampaignImpact> => {
  return readCampaignImpact(await analytics(ctx), ctx.Tokens.Sql, filtersJson);
}, []);
udf.func('businessPage',async(view:string,ctx:RayfinContext<AppSchema,AudienceType.Sql>):Promise<GoldPages>=>{
  const scope=goldView(view);
  return readGoldPages(await analytics(ctx),ctx.Tokens.Sql,scope);
},[]);
async function ontologyBinding(ctx:RayfinContext<AppSchema>){
  const[operational,configured,gold]=await Promise.all([binding(ctx),ctx.getDataClient().OntologyBinding.select(['id','binding_key','workspace_id','ontology_id',
    'graph_model_id','gold_item_id','verified']).where({binding_key:{eq:'business-ontology-v2'}}).execute(),
    ctx.getDataClient().AnalyticsBinding.select(['item_id','workspace_id','verified']).where({binding_key:{eq:'business-gold'}}).execute()]);
  if(configured.length!==1||!configured[0].verified||configured[0].workspace_id!==operational.workspace_id
    ||gold.length!==1||!gold[0].verified||gold[0].workspace_id!==operational.workspace_id
    ||configured[0].gold_item_id!==gold[0].item_id)
    throw new Error('Verified ontology v2 binding missing. No operational graph fallback.');
  return configured[0];
}
udf.func('businessGraph',async(ctx:RayfinContext<AppSchema,AudienceType.Fabric>):Promise<OntologyGraph>=>{
  return readOntologyGraph(await ontologyBinding(ctx),ctx.Tokens.Fabric,50);
},[]);
udf.func('businessGraphSlice',async(journeyLimit:number,ctx:RayfinContext<AppSchema,AudienceType.Fabric>):Promise<OntologyGraph>=>{
  return readOntologyGraph(await ontologyBinding(ctx),ctx.Tokens.Fabric,journeyLimit);
},[]);
udf.func('flixyAsk', async (question: string, historyJson: string,
  ctx: RayfinContext<AppSchema, AudienceType.Fabric>): Promise<FlixyAnswer> => {
  const grants = await ctx.getDataClient().FlixyAccessGrant
    .select(['enabled', 'entra_object_id', 'tenant_id']).execute();
  if (grants.length !== 1) throw new Error("Named user access to Flixy is required. The owner's permissions are not shared.");
  assertFlixyIdentity(grants[0], ctx.Tokens.Fabric);
  const operational = await binding(ctx);
  const [links, gold, ontology] = await Promise.all([
    ctx.getDataClient().IntegrationLink.select(['type', 'url']).where({ link_key: { eq: 'flixy-data-agent' } }).execute(),
    ctx.getDataClient().AnalyticsBinding.select(['item_id', 'workspace_id', 'verified'])
      .where({ binding_key: { eq: 'business-gold' } }).execute(),
    ctx.getDataClient().OntologyBinding.select(['workspace_id', 'graph_model_id', 'gold_item_id', 'verified'])
      .where({ binding_key: { eq: 'business-ontology-v2' } }).execute(),
  ]);
  if (links.length !== 1 || links[0].type !== 'DataAgent' || gold.length !== 1 || ontology.length !== 1
    || !gold[0].verified || !ontology[0].verified || gold[0].workspace_id !== operational.workspace_id
    || ontology[0].workspace_id !== operational.workspace_id || ontology[0].gold_item_id !== gold[0].item_id)
    throw new Error("The cockpit's Flixy source bindings are not verified.");
  return askNativeFlixy({
    tenant_id: grants[0].tenant_id,
    workspace_id: operational.workspace_id,
    data_agent_id: flixyAgentId(links[0].url, operational.workspace_id),
    warehouse_id: gold[0].item_id, graph_id: ontology[0].graph_model_id,
  }, ctx.Tokens.Fabric, question, historyJson);
}, []);
udf.func('placeOrder', async (input: OrderInput,
  ctx: RayfinContext<AppSchema, AudienceType.Sql>): Promise<CommandResult> =>
  run(ctx, input.idempotency_key, 'placeOrder', input, store => commands.placeOrder(store, input)), []);
udf.func('startPlayback', async (input: PlayInput,
  ctx: RayfinContext<AppSchema, AudienceType.Sql>): Promise<CommandResult> =>
  run(ctx, input.idempotency_key, 'startPlayback', input, store => commands.startPlayback(store, input)), []);
udf.func('recordProgress', async (input: ProgressInput,
  ctx: RayfinContext<AppSchema, AudienceType.Sql>): Promise<CommandResult> =>
  run(ctx, input.idempotency_key, 'recordProgress', input, store => commands.recordProgress(store, input)), []);
udf.func('expireRentals', async (idempotency_key: string,
  ctx: RayfinContext<AppSchema, AudienceType.Sql>): Promise<CommandResult> =>
  run(ctx, idempotency_key, 'expireRentals', {}, store => commands.expireRentals(store)), []);
udf.func('requestControl', async (input: ControlInput,
  ctx: RayfinContext<AppSchema, AudienceType.Sql>): Promise<CommandResult> =>
  run(ctx, input.idempotency_key, 'requestControl', input, store => commands.requestControl(store, input)), []);
