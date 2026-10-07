export type OntologyConfig={workspace_id:string;ontology_id:string;graph_model_id:string;gold_item_id:string};
export type OntologyGraph={source:OntologyConfig;state:'ready'|'empty'|'pending'|'binding-mismatch';
  queried_at:string;generation:number;message:string;nodes:{key:string;type:string;label:string}[];
  edges:{from:string;to:string;type:string}[];limit:number};
const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;
async function api(url:string,token:string,body?:unknown):Promise<Response>{
  return fetch(url,{method:body?'POST':'GET',headers:{Authorization:`Bearer ${token}`,
    'Content-Type':'application/json',Accept:'application/json','x-ms-fabric-skill':'fabriciq-ontology-cli'},
    body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(30000)});
}
export async function readOntologyGraph(config:OntologyConfig,token:string):Promise<OntologyGraph>{
  const source={workspace_id:config.workspace_id,ontology_id:config.ontology_id,
    graph_model_id:config.graph_model_id,gold_item_id:config.gold_item_id};
  if(Object.values(source).some(value=>!uuid.test(value)))throw new Error('Ontology graph binding is invalid.');
  const base='https://api.fabric.microsoft.com/v1';
  const empty={source,queried_at:new Date().toISOString(),generation:2,nodes:[],edges:[],limit:50};
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
  const query='MATCH (c:customer)-[:customer_order]->(r:rental)-[:order_offer]->(o:offer)-[:offer_content]->(f:content) RETURN c.customer_key AS customer_key, c.name AS customer_name, r.order_id AS order_id, o.offer_key AS offer_key, f.content_key AS content_key, f.title AS title LIMIT 50';
  let continuation:string|undefined;let body:{status?:{code:string;description?:string};result?:{data?:Record<string,unknown>[];nextPage?:string}}|undefined;
  for(let i=0;i<8;i++){
    const suffix=continuation?`&continuationToken=${encodeURIComponent(continuation)}`:'';
    const response=await api(`${base}/workspaces/${config.workspace_id}/graphModels/${config.graph_model_id}/executeQuery?beta=true${suffix}`,token,{query});
    const json=await response.json() as typeof body&{errorCode?:string;message?:string};
    if(response.status===400&&json?.errorCode==='GraphNotQueryable')
      return{...empty,state:'pending',message:'The real graph is not queryable yet; parent must complete its initial load/refresh.'};
    if(!response.ok)throw new Error(`Ontology graph query failed (${response.status}, ${json?.errorCode??'HTTP_ERROR'}).`);
    body=json;
    if(!['00000','02000'].includes(body?.status?.code??''))throw new Error(`Graph query did not succeed (${body?.status?.code??'NO_STATUS'}). ${body?.status?.description??''}`);
    continuation=body?.result?.nextPage;
    if(!continuation)break;
    await new Promise(resolve=>setTimeout(resolve,2000));
  }
  if(continuation)return{...empty,state:'pending',message:'The bounded graph query is still running; no invented instances are displayed.'};
  const rows=body?.result?.data??[];
  const nodes=new Map<string,{key:string;type:string;label:string}>();const edges=new Map<string,{from:string;to:string;type:string}>();
  for(const row of rows){
    const chain=[['customer',row.customer_key,row.customer_name],['rental',row.order_id,row.order_id],
      ['offer',row.offer_key,row.offer_key],['content',row.content_key,row.title]];
    if(chain.some(([,key])=>typeof key!=='string'))throw new Error('Graph result does not match the declared business key projection.');
    chain.forEach(([type,key,label])=>nodes.set(`${type}:${key}`,{key:`${type}:${key}`,type:String(type),label:String(label??key)}));
    ['customer_order','order_offer','offer_content'].forEach((type,index)=>{
      const from=`${chain[index][0]}:${chain[index][1]}`;const to=`${chain[index+1][0]}:${chain[index+1][1]}`;
      edges.set(`${from}:${to}`,{from,to,type});
    });
  }
  return{...empty,state:rows.length?'ready':'empty',message:rows.length?'Actual GraphModel query instances':'The real graph query returned no relationship instances.',
    nodes:[...nodes.values()],edges:[...edges.values()]};
}
