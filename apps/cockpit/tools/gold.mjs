/** Gold coordinate validation/binding and the same read-only dashboard reader as native UDF. */
import{readFile}from'node:fs/promises';
import{createRequire}from'node:module';
import{parseArgs}from'node:util';
import{readGoldDashboard}from'../rayfin/functions/dist/src/gold-dashboard.js';
import{poolFor}from'../rayfin/functions/dist/src/storage.js';
import{canonical}from'../rayfin/functions/dist/src/domain.js';
const require=createRequire(new URL('../rayfin/functions/package.json',import.meta.url));
const sql=require('mssql');const{DefaultAzureCredential}=require('@azure/identity');
const{values,positionals}=parseArgs({allowPositionals:true,options:{
  binding:{type:'string',default:'tools/binding.live.local.json'},
  gold:{type:'string',default:'tools/gold.binding.live.local.json'}}});
if(!['bind','read'].includes(positionals[0])||positionals.length!==1)throw new Error('Usage: node tools/gold.mjs bind|read');
const operational=JSON.parse(await readFile(values.binding,'utf8'));
const gold=JSON.parse(await readFile(values.gold,'utf8'));
if(gold.workspace_id!==operational.workspace_id || gold.capacity_id!==operational.capacity_id)
  throw new Error('Gold must be in the approved operational app workspace/capacity.');
const credential=new DefaultAzureCredential({tenantId:operational.tenant_id});
let pool;
try{
  if(positionals[0]==='bind'){
    const token=await credential.getToken('https://api.fabric.microsoft.com/.default');
    const headers={Authorization:`Bearer ${token.token}`,'x-ms-fabric-skill':'rayfin'};
    const base=`https://api.fabric.microsoft.com/v1/workspaces/${gold.workspace_id}`;
    const workspaceResponse=await fetch(base,{headers});
    if(!workspaceResponse.ok)throw new Error(`Workspace validation failed (${workspaceResponse.status}).`);
    const workspace=await workspaceResponse.json();
    if(workspace.displayName!=='MSFlix'||workspace.capacityId!==gold.capacity_id)throw new Error('Gold workspace/capacity changed.');
    const itemResponse=await fetch(`${base}/warehouses/${gold.item_id}`,{headers});
    if(!itemResponse.ok)throw new Error(`Gold item validation failed (${itemResponse.status}).`);
    const item=await itemResponse.json();
    if(item.id!==gold.item_id || item.displayName!=='MSFlixGold' || item.type!=='Warehouse' ||
      item.properties.connectionString!==gold.sql_server || gold.sql_database!==gold.item_id)
      throw new Error('Actual Gold coordinates do not match the declared binding.');
    const sqlToken=await credential.getToken('https://database.windows.net/.default');
    pool=await poolFor(operational,sqlToken.token);
    const fields=['binding_key','name','sql_server','sql_database','item_id','workspace_id','capacity_id'];
    const request=pool.request().input('id',sql.UniqueIdentifier,gold.id);
    fields.forEach((field,i)=>request.input(`p${i}`,sql.NVarChar(field==='sql_server'?300:field==='name'?160:field==='binding_key'?64:128),gold[field]));
    await request.query(`IF EXISTS (SELECT 1 FROM dbo.AnalyticsBindings WHERE binding_key=@p0)
      UPDATE dbo.AnalyticsBindings SET ${fields.slice(1).map((field,i)=>`[${field}]=@p${i+1}`).join(',')},verified=1 WHERE binding_key=@p0
      ELSE INSERT dbo.AnalyticsBindings (id,${fields.map(field=>`[${field}]`).join(',')},verified)
        VALUES (@id,${fields.map((_,i)=>`@p${i}`).join(',')},1)`);
    console.log(canonical({coordinates_verified:true,binding_persisted:true,item_id:gold.item_id,source:gold.name,
      gold_load_qualified:false}));
  }else{
    const token=await credential.getToken('https://database.windows.net/.default');
    const result=await readGoldDashboard(gold,token.token);
    console.log(canonical(result));
  }
}catch(error){
  console.error(canonical({gold_dashboard_verified:false,error:String(error.message).slice(0,700),operational_fallback:false}));
  process.exitCode=1;
}finally{if(pool)await pool.close();}
