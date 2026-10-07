/**
 * Two-source live SQL validation, ALWAYS rolled back. This checks the actual
 * set-based SQL and canonical outbox writer without committing demo volume.
 */
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { randomUUID } from 'node:crypto';
import { parseArgs } from 'node:util';
import { poolFor, emitMany } from '../rayfin/functions/dist/src/storage.js';
import { writeSourceBatch } from '../rayfin/functions/dist/src/volume-batch.js';
import { stableUuid } from '../rayfin/functions/dist/src/volume-domain.js';
const require=createRequire(new URL('../rayfin/functions/package.json',import.meta.url));
const sql=require('mssql');
const {DefaultAzureCredential}=require('@azure/identity');
const {values}=parseArgs({options:{binding:{type:'string',default:'tools/binding.live.local.json'}}});
const b=JSON.parse(await readFile(values.binding,'utf8'));
const token=await new DefaultAzureCredential({tenantId:b.tenant_id}).getToken('https://database.windows.net/.default');
const pool=await poolFor(b,token.token);
let tx;
let verified;
try{
  const selected=await pool.request().query(`SELECT TOP (2) customer.customer_key,o.offer_key,o.price_minor,o.currency,
    c.duration_seconds FROM dbo.Customers customer JOIN dbo.Offers o ON o.territory=customer.territory
    JOIN dbo.Contents c ON c.content_key=o.content_key
    WHERE o.transaction_type='TVOD' AND c.duration_seconds>=7 ORDER BY customer.customer_key,o.offer_key`);
  if(selected.recordset.length!==2)throw new Error('Two actual eligible source transactions are required.');
  const run=`verify-${randomUUID()}`;
  const rows=selected.recordset.map((row,index)=>({ordinal:index,source_transaction_key:`${run}/${index}`,
    customer_key:row.customer_key,offer_key:row.offer_key,
    order_id:stableUuid(`${run}:order:${index}`),session_id:stableUuid(`${run}:session:${index}`)}));
  tx=new sql.Transaction(pool);await tx.begin(sql.ISOLATION_LEVEL.SERIALIZABLE);
  const store={tx,now:new Date(),runId:run,correlationId:run};
  const changes=await writeSourceBatch(store,rows,7);
  if(changes.length!==20)throw new Error('Unexpected live SQL state-change count.');
  for(let index=0;index<rows.length;index++){
    const states=changes.filter(change=>change.source_transaction_key===rows[index].source_transaction_key);
    const order=JSON.parse(states.find(s=>s.phase===0).payload_json);
    const source=selected.recordset[index];
    if(order.amount_minor!==source.price_minor || order.currency!==source.currency || order.status!=='booked')
      throw new Error('Persisted order did not retain actual server policy.');
    const progress=states.filter(s=>s.event_type==='playback.updated').map(s=>JSON.parse(s.payload_json));
    if(progress.length!==7 || progress[6].position_seconds!==source.duration_seconds || progress[6].status!=='completed' ||
      progress.some((p,i)=>i>0 && p.position_seconds<=progress[i-1].position_seconds))
      throw new Error('Actual progress writes are not strictly increasing to completion.');
  }
  await emitMany(store,changes.map(change=>({event_type:change.event_type,entity_key:change.entity_key,
    payload:JSON.parse(change.payload_json)})));
  verified={source_transactions:2,state_changes:20,server_policy:true,strict_progress:true,canonical_outbox:true};
}catch(error){
  console.error(JSON.stringify({verified:false,code:error.code??'SQL_VOLUME_VALIDATION_FAILED',
    message:String(error.message).slice(0,500)}));process.exitCode=1;
}finally{
  if(tx){try{await tx.rollback();}catch{verified=undefined;process.exitCode=1;}}
  await pool.close();
}
if(verified)console.log(JSON.stringify({verified:true,rolled_back:true,...verified,persisted_test_orders:0,persisted_test_events:0}));
