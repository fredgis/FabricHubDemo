export type OntologyConfig={workspace_id:string;ontology_id:string;graph_model_id:string;gold_item_id:string;verified?:boolean};
export type OntologyGraphNode = {
  key: string; type: string; label: string;
  created_at?: string; status?: string; amount_minor?: number; currency?: string;
  position_seconds?: number;
};
export type OntologyGraph = {
  source: OntologyConfig; state: 'ready' | 'empty' | 'pending' | 'binding-mismatch';
  queried_at: string; generation: number; message: string;
  nodes: OntologyGraphNode[]; edges: { from: string; to: string; type: string }[]; limit: number;
  context?: { playback_limit: number; playback_truncated: boolean; distributor_limit: number; distributors_truncated: boolean };
};
const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;
const qualifiedDefinitions=new Map<string,number>();
const METADATA_TTL_MS=120000;
async function api(url:string,token:string,body?:unknown,timeoutMs=30000):Promise<Response>{
  return fetch(url,{method:body?'POST':'GET',headers:{Authorization:`Bearer ${token}`,
    'Content-Type':'application/json',Accept:'application/json','x-ms-fabric-skill':'fabriciq-ontology-cli'},
    body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(timeoutMs)});
}
type GraphRow = Record<string, unknown>;
type GraphPhase = 'read' | 'metadata' | 'orders' | 'distributors' | 'playback' | 'assemble_orders' | 'assemble_context';
type GraphDiagnosticFields = {
  state?: OntologyGraph['state']; mode?: 'verified' | 'cached' | 'read';
  request_count?: number; continuation_count?: number; poll_count?: number; row_count?: number;
  node_count?: number; edge_count?: number; http_status?: number; graph_status?: string;
  timeout_ms?: number; headers_ms?: number; body_ms?: number; wait_ms?: number; delay_ms?: number;
  has_next_page?: boolean; page_row_count?: number;
  reason?: 'deadline' | 'continuation_limit' | 'not_queryable';
  failure_stage?: 'request' | 'body' | 'status' | 'rows';
  error_kind?: 'timeout' | 'aborted' | 'invalid_json' | 'error';
};
function graphErrorKind(error: unknown): GraphDiagnosticFields['error_kind'] {
  try {
    const name = (error as { name?: unknown } | null)?.name;
    if (name === 'TimeoutError') return 'timeout';
    if (name === 'AbortError') return 'aborted';
    if (name === 'SyntaxError') return 'invalid_json';
  } catch { /* Diagnostics must not replace the original failure. */ }
  return 'error';
}
function createGraphDiagnostics() {
  const readId = randomUUID();
  const readStarted = performance.now();
  return (phase: GraphPhase) => {
    const phaseStarted = performance.now();
    const emit = (status: 'start' | 'complete' | 'failed' | 'request' | 'headers' | 'response' | 'wait' | 'pending', fields: GraphDiagnosticFields = {}) => {
      try {
        const now = performance.now();
        // Only counts, timings and classified statuses belong here, never payloads or exception text.
        console.log(JSON.stringify({ event: 'business_graph', read_id: readId, phase, status,
          elapsed_ms: Math.round(now - readStarted), phase_ms: Math.round(now - phaseStarted), ...fields }));
      } catch { /* Logging is not part of graph correctness. */ }
    };
    emit('start');
    return emit;
  };
}
const CONTEXT_LIMIT = 200;
function businessKey(row: GraphRow, name: string): string {
  const value = row[name];
  // Keys are interpolated only into bounded GQL IN lists; reject unsupported literals before querying.
  if (typeof value !== 'string' || !/^[A-Za-z0-9_.:@/-]{1,256}$/.test(value)) {
    throw new Error(`Graph result contains an invalid business key (${name}).`);
  }
  return value;
}
function textValue(row: GraphRow, name: string): string {
  const value = row[name];
  if (typeof value !== 'string' || !value.trim()) throw new Error(`Graph result contains an invalid ${name}.`);
  return value;
}
function integerValue(row: GraphRow, name: string): number {
  const value = row[name];
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) {
    throw new Error(`Graph result contains an invalid ${name}.`);
  }
  return value;
}
export async function readOntologyGraph(config:OntologyConfig,token:string,limit=12):Promise<OntologyGraph>{
  const trace = createGraphDiagnostics();
  const read = trace('read');
  try {
    const result = await readGraph(config, token, limit, trace);
    read('complete', { state: result.state, node_count: result.nodes.length, edge_count: result.edges.length });
    return result;
  } catch (error) {
    read('failed', { error_kind: graphErrorKind(error) });
    throw error;
  }
}
async function readGraph(config: OntologyConfig, token: string, limit: number,
  trace: ReturnType<typeof createGraphDiagnostics>): Promise<OntologyGraph> {
  const source={workspace_id:config.workspace_id,ontology_id:config.ontology_id,
    graph_model_id:config.graph_model_id,gold_item_id:config.gold_item_id};
  if(Object.values(source).some(value=>!uuid.test(value)))throw new Error('Ontology graph binding is invalid.');
  if(![6,12,24,50].includes(limit))throw new Error('Graph journey limit must be 6, 12, 24 or 50.');
  const base='https://api.fabric.microsoft.com/v1';
  const empty={source,queried_at:new Date().toISOString(),generation:2,nodes:[],edges:[],limit};
  const metadata = trace('metadata');
  const metadataStats: GraphDiagnosticFields = { request_count: 0, poll_count: 0 };
  const definitionRequest = async (url: string, body?: unknown) => {
    metadataStats.request_count!++;
    metadataStats.http_status = undefined;
    metadata('request', metadataStats);
    const response = await api(url, token, body);
    metadataStats.http_status = response.status;
    metadata('response', metadataStats);
    return response;
  };
  try {
    const metadataKey=createHash('sha256').update(JSON.stringify(source)).update(token).digest('hex');
    for(const[key,expires]of qualifiedDefinitions)if(expires<=Date.now())qualifiedDefinitions.delete(key);
    metadataStats.mode = config.verified === true ? 'verified' : qualifiedDefinitions.has(metadataKey) ? 'cached' : 'read';
    // Native UDFs obtain this flag from the read-only, administrator-qualified binding.
    // Standalone/unqualified callers still validate the full definition before querying.
    if(config.verified!==true&&!qualifiedDefinitions.has(metadataKey)){
      let definition=await definitionRequest(`${base}/workspaces/${config.workspace_id}/items/${config.ontology_id}/getDefinition`,{});
      if(definition.status===202){
        const operation=definition.headers.get('x-ms-operation-id');
        if(!operation||!uuid.test(operation))throw new Error('Ontology definition returned no valid operation ID.');
        for(let i=0;i<8;i++){
          await new Promise(resolve=>setTimeout(resolve,2000));
          metadataStats.poll_count!++;
          const response=await definitionRequest(`${base}/operations/${operation}`);
          if(!response.ok)throw new Error(`Ontology definition poll failed (${response.status}).`);
          const status=await response.json() as{status:string};
          if(status.status==='Failed'||status.status==='Cancelled')throw new Error(`Ontology definition ${status.status}.`);
          if(status.status==='Succeeded'){definition=await definitionRequest(`${base}/operations/${operation}/result`);break;}
        }
      }
      if(!definition.ok)throw new Error(`Ontology definition unavailable (${definition.status}).`);
      const envelope=await definition.json() as{definition?:{parts:{path:string;payload:string}[]};parts?:{path:string;payload:string}[]};
      const parts=envelope.definition?.parts??envelope.parts??[];
      const decode=(path:string)=>Buffer.from(parts.find(part=>part.path===path)?.payload??'','base64').toString('utf8');
      const expression=decode('expressions.tmdl');
      if(!parts.some(part=>part.path==='entities/customer.tmdl')||!parts.some(part=>part.path==='entityRelationships.tmdl'))
        throw new Error('Ontology generation-two entity/relationship definition is not available.');
      if(!expression.includes(config.gold_item_id)) {
        metadata('complete', { ...metadataStats, state: 'binding-mismatch' });
        return{...empty,state:'binding-mismatch',message:'Ontology v2 is not yet bound to the consolidated Gold Warehouse. No operational graph substitution.'};
      }
      if(qualifiedDefinitions.size>=16)qualifiedDefinitions.delete(qualifiedDefinitions.keys().next().value!);
      qualifiedDefinitions.set(metadataKey,Date.now()+METADATA_TTL_MS);
    }
    metadata('complete', metadataStats);
  } catch (error) {
    metadata('failed', { ...metadataStats, error_kind: graphErrorKind(error) });
    throw error;
  }
  const queryDeadline = Date.now() + 45000;
  const queryRows = async (phase: 'orders' | 'distributors' | 'playback', query: string, rowLimit: number): Promise<GraphRow[] | undefined> => {
    const log = trace(phase);
    const stats = { request_count: 0, continuation_count: 0, row_count: 0, wait_ms: 0,
      http_status: undefined as number | undefined, graph_status: undefined as string | undefined };
    let stage: GraphDiagnosticFields['failure_stage'] = 'request';
    let bodyStarted = 0;
    let continuation: string | undefined;
    const rows = new Map<string, GraphRow>();
    try {
      for (let attempt = 0; attempt < 8; attempt++) {
        const remaining = queryDeadline - Date.now();
        if (remaining <= 0) { log('pending', { ...stats, reason: 'deadline' }); return undefined; }
        const suffix = continuation ? `&continuationToken=${encodeURIComponent(continuation)}` : '';
        const timeoutMs = Math.min(30000, remaining);
        stage = 'request';
        stats.request_count++;
        stats.http_status = undefined; stats.graph_status = undefined;
        log('request', { ...stats, timeout_ms: timeoutMs });
        const requestStarted = performance.now();
        const response = await api(`${base}/workspaces/${source.workspace_id}/graphModels/${source.graph_model_id}/executeQuery?beta=true${suffix}`, token, { query }, timeoutMs);
        stats.http_status = response.status;
        log('headers', { ...stats, headers_ms: Math.round(performance.now() - requestStarted) });
        stage = 'body'; bodyStarted = performance.now();
        const body = await response.json() as {
          status?: { code: string }; result?: { data?: GraphRow[]; nextPage?: string }; errorCode?: string;
        };
        const code = body?.status?.code;
        stats.graph_status = typeof code === 'string' && /^[A-Z0-9]{5}$/.test(code) ? code : undefined;
        log('response', { ...stats, body_ms: Math.round(performance.now() - bodyStarted),
          has_next_page: Boolean(body?.result?.nextPage),
          page_row_count: Array.isArray(body?.result?.data) ? body.result.data.length : undefined });
        stage = 'status';
        if (response.status === 400 && body.errorCode === 'GraphNotQueryable') {
          log('pending', { ...stats, reason: 'not_queryable' }); return undefined;
        }
        if (!response.ok) throw new Error(`Ontology graph query failed (${response.status}, ${body.errorCode ?? 'HTTP_ERROR'}).`);
        if (!['00000', '02000'].includes(body.status?.code ?? '')) {
          throw new Error(`Graph query did not succeed (${body.status?.code ?? 'NO_STATUS'}).`);
        }
        stage = 'rows';
        const page = body.result?.data ?? [];
        if (!Array.isArray(page)) throw new Error('Graph query returned an invalid row collection.');
        for (const row of page) {
          if (!row || typeof row !== 'object' || Array.isArray(row)) throw new Error('Graph query returned an invalid row.');
          rows.set(JSON.stringify(row), row);
        }
        stats.row_count = rows.size;
        if (rows.size > rowLimit) throw new Error('Graph query exceeded its declared row limit.');
        continuation = body.result?.nextPage;
        if (!continuation) { log('complete', stats); return [...rows.values()]; }
        stats.continuation_count++;
        if (attempt < 7) {
          const delayMs = Math.min(2000, Math.max(0, queryDeadline - Date.now()));
          log('wait', { ...stats, delay_ms: delayMs });
          const waitStarted = performance.now();
          await new Promise(resolve => setTimeout(resolve, delayMs));
          stats.wait_ms += Math.round(performance.now() - waitStarted);
        }
      }
      log('pending', { ...stats, reason: 'continuation_limit' });
      return undefined;
    } catch (error) {
      log('failed', { ...stats, failure_stage: stage, error_kind: graphErrorKind(error),
        body_ms: stage === 'body' ? Math.round(performance.now() - bodyStarted) : undefined });
      throw error;
    }
  };
  const pending: OntologyGraph = { ...empty, state: 'pending',
    message: 'The real GraphModel is not ready or the bounded read is still running. Refresh graph to retry; no partial graph is presented as complete.' };
  const rows = await queryRows('orders', `MATCH (c:customer)-[:customer_order]->(r:rental)-[:order_offer]->(o:offer)-[:offer_content]->(f:content)
RETURN c.customer_key AS customer_key, c.name AS customer_name,
       r.order_id AS order_id, r.created_at AS created_at,
       r.status AS order_status, r.amount_minor AS amount_minor, r.currency AS currency,
       o.offer_key AS offer_key, f.content_key AS content_key, f.title AS title
ORDER BY r.created_at DESC, r.order_id DESC
LIMIT ${limit}`, limit);
  if (!rows) return pending;
  if (!rows.length) return { ...empty, state: 'empty', message: 'No complete customer-to-film order paths are published in the GraphModel yet. Wait for Gold publication and the Ontology refresh, then use Refresh graph.' };

  const nodes = new Map<string, OntologyGraphNode>();
  const edges = new Map<string, OntologyGraph['edges'][number]>();
  const orders = new Map<string, { customer: string; film: string }>();
  const films = new Set<string>();
  const addEdge = (from: string, to: string, type: string) => edges.set(`${from}|${type}|${to}`, { from, to, type });
  const assembleOrders = trace('assemble_orders');
  try {
  for (const row of rows) {
    const customer = businessKey(row, 'customer_key');
    const order = businessKey(row, 'order_id');
    const offer = businessKey(row, 'offer_key');
    const film = businessKey(row, 'content_key');
    const created = textValue(row, 'created_at');
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$/.test(created) || !Number.isFinite(Date.parse(created))) {
      throw new Error('Graph result contains an invalid UTC order creation timestamp.');
    }
    const currency = textValue(row, 'currency');
    if (!/^[A-Z]{3}$/.test(currency)) throw new Error('Graph result contains an invalid currency.');
    if (orders.has(order)) throw new Error('Graph result contains multiple paths for the same order.');
    orders.set(order, { customer, film }); films.add(film);
    nodes.set(`customer:${customer}`, { key: `customer:${customer}`, type: 'customer', label: textValue(row, 'customer_name') });
    nodes.set(`rental:${order}`, { key: `rental:${order}`, type: 'rental', label: order,
      created_at: created, status: textValue(row, 'order_status'), amount_minor: integerValue(row, 'amount_minor'), currency });
    nodes.set(`offer:${offer}`, { key: `offer:${offer}`, type: 'offer', label: offer });
    nodes.set(`content:${film}`, { key: `content:${film}`, type: 'content', label: textValue(row, 'title') });
    addEdge(`customer:${customer}`, `rental:${order}`, 'customer_order');
    addEdge(`rental:${order}`, `offer:${offer}`, 'order_offer');
    addEdge(`offer:${offer}`, `content:${film}`, 'offer_content');
  }
  assembleOrders('complete', { node_count: nodes.size, edge_count: edges.size });
  } catch (error) {
    assembleOrders('failed', { error_kind: graphErrorKind(error) });
    throw error;
  }
  const literals = (keys: Iterable<string>) => `[${[...keys].map(key => `'${key}'`).join(', ')}]`;
  // Expand only after selecting the newest orders so 1:N sessions cannot consume the order limit.
  const [distributors, sessions] = await Promise.all([
    queryRows('distributors', `MATCH (f:content)-[:content_distributor]->(d:distributor)
WHERE f.content_key IN ${literals(films)}
RETURN f.content_key AS content_key, d.distributor_key AS distributor_key, d.name AS distributor_name
ORDER BY f.content_key, d.distributor_key
LIMIT ${CONTEXT_LIMIT + 1}`, CONTEXT_LIMIT + 1),
    queryRows('playback', `MATCH (r:rental)<-[:playback_order]-(p:playback)-[:playback_content]->(f:content)
WHERE r.order_id IN ${literals(orders.keys())}
RETURN p.session_id AS session_id, r.order_id AS order_id,
       f.content_key AS content_key, p.customer_key AS customer_key,
       p.order_id AS playback_order_id, p.content_key AS playback_content_key,
       p.status AS playback_status, p.position_seconds AS position_seconds
ORDER BY r.order_id, p.session_id, f.content_key
LIMIT ${CONTEXT_LIMIT + 1}`, CONTEXT_LIMIT + 1),
  ]);
  if (!distributors || !sessions) return pending;
  const assembleContext = trace('assemble_context');
  try {
  for (const row of distributors.slice(0, CONTEXT_LIMIT)) {
    const film = businessKey(row, 'content_key');
    const distributor = businessKey(row, 'distributor_key');
    if (!films.has(film)) throw new Error('Graph distributor relationship is outside the selected films.');
    nodes.set(`distributor:${distributor}`, { key: `distributor:${distributor}`, type: 'distributor', label: textValue(row, 'distributor_name') });
    addEdge(`content:${film}`, `distributor:${distributor}`, 'content_distributor');
  }
  const sessionOrders = new Map<string, string>();
  for (const row of sessions.slice(0, CONTEXT_LIMIT)) {
    const session = businessKey(row, 'session_id');
    const order = businessKey(row, 'order_id');
    const film = businessKey(row, 'content_key');
    const selected = orders.get(order);
    if (!selected || selected.film !== film || selected.customer !== businessKey(row, 'customer_key')
      || businessKey(row, 'playback_order_id') !== order || businessKey(row, 'playback_content_key') !== film
      || (sessionOrders.has(session) && sessionOrders.get(session) !== order)) {
      throw new Error('Graph playback relationship does not match a selected order, customer and film.');
    }
    sessionOrders.set(session, order);
    nodes.set(`playback:${session}`, { key: `playback:${session}`, type: 'playback', label: session,
      status: textValue(row, 'playback_status'), position_seconds: integerValue(row, 'position_seconds') });
    addEdge(`playback:${session}`, `rental:${order}`, 'playback_order');
    addEdge(`playback:${session}`, `content:${film}`, 'playback_content');
  }
  assembleContext('complete', { node_count: nodes.size, edge_count: edges.size });
  } catch (error) {
    assembleContext('failed', { error_kind: graphErrorKind(error) });
    throw error;
  }
  return { ...empty, state: 'ready', message: 'Newest published orders and their actual ontology relationships.',
    nodes: [...nodes.values()], edges: [...edges.values()], context: {
      playback_limit: CONTEXT_LIMIT, playback_truncated: sessions.length > CONTEXT_LIMIT,
      distributor_limit: CONTEXT_LIMIT, distributors_truncated: distributors.length > CONTEXT_LIMIT,
    } };
}
import { createHash, randomUUID } from 'node:crypto';
