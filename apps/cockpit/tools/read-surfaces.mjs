/** Cached noninteractive authoring verification of the SAME native read functions. */
import{readFile}from'node:fs/promises';
import{createRequire}from'node:module';
import{parseArgs}from'node:util';
import{readGoldPages}from'../rayfin/functions/dist/src/gold-pages.js';
import{readOntologyGraph}from'../rayfin/functions/dist/src/ontology-graph.js';
import{poolFor}from'../rayfin/functions/dist/src/storage.js';
const require=createRequire(new URL('../rayfin/functions/package.json',import.meta.url));
const sql=require('mssql');const{DefaultAzureCredential}=require('@azure/identity');
const{positionals}=parseArgs({allowPositionals:true});
if(!['gold','graph','bind-graph'].includes(positionals[0]))throw new Error('Usage: read-surfaces.mjs gold|graph|bind-graph');
const operational=JSON.parse(await readFile('tools/binding.live.local.json','utf8'));
const credential=new DefaultAzureCredential({tenantId:operational.tenant_id});
try{
  if(positionals[0]==='gold'){
    const binding=JSON.parse(await readFile('tools/gold.binding.live.local.json','utf8'));
    const token=await credential.getToken('https://database.windows.net/.default');
    const result=await readGoldPages(binding,token.token);
    console.log(JSON.stringify({source:result.dashboard.source,state:result.dashboard.state,freshness:result.dashboard.freshness,
      rows:{catalog:result.catalog.length,customers:result.customers.length,offers:result.offers.length,
        orders:result.orders.length,sessions:result.sessions.length,campaigns:result.campaigns.length},window:result.window}));
  }else{
    const binding=JSON.parse(await readFile('tools/ontology.binding.live.local.json','utf8'));
    const token=await credential.getToken('https://api.fabric.microsoft.com/.default');
    if(positionals[0]==='graph'){
      console.log(JSON.stringify(await readOntologyGraph(binding,token.token)));
    }else{
      if(binding.workspace_id!==operational.workspace_id||!binding.verified)throw new Error('Ontology binding is outside app scope.');
      const headers={Authorization:`Bearer ${token.token}`,'x-ms-fabric-skill':'fabriciq-ontology-cli'};
      for(const[id,type]of[[binding.ontology_id,'Ontology'],[binding.graph_model_id,'GraphModel']]){
        const response=await fetch(`https://api.fabric.microsoft.com/v1/workspaces/${binding.workspace_id}/items/${id}`,{headers});
        if(!response.ok)throw new Error(`Graph item validation ${response.status}`);
        const item=await response.json();if(item.id!==id||item.type!==type)throw new Error('Graph/ontology item type mismatch.');
      }
      const sqlToken=await credential.getToken('https://database.windows.net/.default');
      const pool=await poolFor(operational,sqlToken.token);
      try{
        await pool.request().input('id',sql.UniqueIdentifier,binding.id).input('key',sql.NVarChar(64),binding.binding_key)
          .input('ws',sql.NVarChar(128),binding.workspace_id).input('ontology',sql.NVarChar(128),binding.ontology_id)
          .input('graph',sql.NVarChar(128),binding.graph_model_id).input('gold',sql.NVarChar(128),binding.gold_item_id)
          .query(`IF NOT EXISTS (SELECT 1 FROM dbo.OntologyBindings WHERE binding_key=@key)
            INSERT dbo.OntologyBindings(id,binding_key,workspace_id,ontology_id,graph_model_id,gold_item_id,verified)
            VALUES(@id,@key,@ws,@ontology,@graph,@gold,1)`);
        console.log(JSON.stringify({binding_persisted:true,items_verified:true,graph_instances_qualified:false}));
      }finally{await pool.close();}
    }
  }
}catch(error){console.error(JSON.stringify({verified:false,error:String(error.message).slice(0,900),no_login_attempted:true}));process.exitCode=1;}
