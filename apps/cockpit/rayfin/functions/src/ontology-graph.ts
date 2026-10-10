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
  const source={workspace_id:config.workspace_id,ontology_id:config.ontology_id,
    graph_model_id:config.graph_model_id,gold_item_id:config.gold_item_id};
  if(Object.values(source).some(value=>!uuid.test(value)))throw new Error('Ontology graph binding is invalid.');
  if(![6,12,24,50].includes(limit))throw new Error('Graph journey limit must be 6, 12, 24 or 50.');
  const base='https://api.fabric.microsoft.com/v1';
  const empty={source,queried_at:new Date().toISOString(),generation:2,nodes:[],edges:[],limit};
  const metadataKey=createHash('sha256').update(JSON.stringify(source)).update(token).digest('hex');
  for(const[key,expires]of qualifiedDefinitions)if(expires<=Date.now())qualifiedDefinitions.delete(key);
  // Native UDFs obtain this flag from the read-only, administrator-qualified binding.
  // Standalone/unqualified callers still validate the full definition before querying.
  if(config.verified!==true&&!qualifiedDefinitions.has(metadataKey)){
  let definition=await api(`${base}/workspaces/${config.workspace_id}/items/${config.ontology_id}/getDefinition`,token,{});
  if(definition.status===202){
    const operation=definition.headers.get('x-ms-operation-id');
    if(!operation||!uuid.test(operation))throw new Error('Ontology definition returned no valid operation ID.');
    for(let i=0;i<8;i++){
      await new Promise(resolve=>setTimeout(resolve,2000));
      const response=await api(`${base}/operations/${operation}`,token);
      if(!response.ok)throw new Error(`Ontology definition poll failed (${response.status}).`);
      const status=await response.json() as{status:string};
      if(status.status==='Failed'||status.status==='Cancelled')throw new Error(`Ontology definition ${status.status}.`);
      if(status.status==='Succeeded'){definition=await api(`${base}/operations/${operation}/result`,token);break;}
    }
  }
  if(!definition.ok)throw new Error(`Ontology definition unavailable (${definition.status}).`);
  const envelope=await definition.json() as{definition?:{parts:{path:string;payload:string}[]};parts?:{path:string;payload:string}[]};
  const parts=envelope.definition?.parts??envelope.parts??[];
  const decode=(path:string)=>Buffer.from(parts.find(part=>part.path===path)?.payload??'','base64').toString('utf8');
  const expression=decode('expressions.tmdl');
  if(!parts.some(part=>part.path==='entities/customer.tmdl')||!parts.some(part=>part.path==='entityRelationships.tmdl'))
    throw new Error('Ontology generation-two entity/relationship definition is not available.');
  if(!expression.includes(config.gold_item_id))
    return{...empty,state:'binding-mismatch',message:'Ontology v2 is not yet bound to the consolidated Gold Warehouse. No operational graph substitution.'};
  if(qualifiedDefinitions.size>=16)qualifiedDefinitions.delete(qualifiedDefinitions.keys().next().value!);
  qualifiedDefinitions.set(metadataKey,Date.now()+METADATA_TTL_MS);
  }
  const queryDeadline = Date.now() + 45000;
  const queryRows = async (query: string, rowLimit: number): Promise<GraphRow[] | undefined> => {
    let continuation: string | undefined;
    const rows = new Map<string, GraphRow>();
    for (let attempt = 0; attempt < 8; attempt++) {
      const remaining = queryDeadline - Date.now();
      if (remaining <= 0) return undefined;
      const suffix = continuation ? `&continuationToken=${encodeURIComponent(continuation)}` : '';
      const response = await api(`${base}/workspaces/${source.workspace_id}/graphModels/${source.graph_model_id}/executeQuery?beta=true${suffix}`, token, { query }, Math.min(30000, remaining));
      const body = await response.json() as {
        status?: { code: string }; result?: { data?: GraphRow[]; nextPage?: string }; errorCode?: string;
      };
      if (response.status === 400 && body.errorCode === 'GraphNotQueryable') return undefined;
      if (!response.ok) throw new Error(`Ontology graph query failed (${response.status}, ${body.errorCode ?? 'HTTP_ERROR'}).`);
      if (!['00000', '02000'].includes(body.status?.code ?? '')) {
        throw new Error(`Graph query did not succeed (${body.status?.code ?? 'NO_STATUS'}).`);
      }
      const page = body.result?.data ?? [];
      if (!Array.isArray(page)) throw new Error('Graph query returned an invalid row collection.');
      for (const row of page) {
        if (!row || typeof row !== 'object' || Array.isArray(row)) throw new Error('Graph query returned an invalid row.');
        rows.set(JSON.stringify(row), row);
      }
      if (rows.size > rowLimit) throw new Error('Graph query exceeded its declared row limit.');
      continuation = body.result?.nextPage;
      if (!continuation) return [...rows.values()];
      if (attempt < 7) await new Promise(resolve => setTimeout(resolve, Math.min(2000, Math.max(0, queryDeadline - Date.now()))));
    }
    return undefined;
  };
  const pending: OntologyGraph = { ...empty, state: 'pending',
    message: 'The real GraphModel is not ready or the bounded read is still running. Refresh graph to retry; no partial graph is presented as complete.' };
  const rows = await queryRows(`MATCH (c:customer)-[:customer_order]->(r:rental)-[:order_offer]->(o:offer)-[:offer_content]->(f:content)
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
  const literals = (keys: Iterable<string>) => `[${[...keys].map(key => `'${key}'`).join(', ')}]`;
  // Expand only after selecting the newest orders so 1:N sessions cannot consume the order limit.
  const [distributors, sessions] = await Promise.all([
    queryRows(`MATCH (f:content)-[:content_distributor]->(d:distributor)
WHERE f.content_key IN ${literals(films)}
RETURN f.content_key AS content_key, d.distributor_key AS distributor_key, d.name AS distributor_name
ORDER BY f.content_key, d.distributor_key
LIMIT ${CONTEXT_LIMIT + 1}`, CONTEXT_LIMIT + 1),
    queryRows(`MATCH (r:rental)<-[:playback_order]-(p:playback)-[:playback_content]->(f:content)
WHERE r.order_id IN ${literals(orders.keys())}
RETURN p.session_id AS session_id, r.order_id AS order_id,
       f.content_key AS content_key, p.customer_key AS customer_key,
       p.order_id AS playback_order_id, p.content_key AS playback_content_key,
       p.status AS playback_status, p.position_seconds AS position_seconds
ORDER BY r.order_id, p.session_id, f.content_key
LIMIT ${CONTEXT_LIMIT + 1}`, CONTEXT_LIMIT + 1),
  ]);
  if (!distributors || !sessions) return pending;
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
  return { ...empty, state: 'ready', message: 'Newest published orders and their actual ontology relationships.',
    nodes: [...nodes.values()], edges: [...edges.values()], context: {
      playback_limit: CONTEXT_LIMIT, playback_truncated: sessions.length > CONTEXT_LIMIT,
      distributor_limit: CONTEXT_LIMIT, distributors_truncated: distributors.length > CONTEXT_LIMIT,
    } };
}
import { createHash } from 'node:crypto';
