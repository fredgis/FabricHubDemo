/** Replays one ALREADY committed chunk only. This tool cannot start fresh volume. */
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { parseArgs } from 'node:util';
import { randomUUID } from 'node:crypto';
import { parseCsv } from './lib/csv.mjs';
import { poolFor } from '../rayfin/functions/dist/src/storage.js';
import { bulkSourceTransactions,runFingerprint } from '../rayfin/functions/dist/src/volume-batch.js';
import { readRun } from '../rayfin/functions/dist/src/volume-runs.js';
import { digest,validateProfile } from '../rayfin/functions/dist/src/volume-domain.js';
import { assertOperator,canonical } from '../rayfin/functions/dist/src/domain.js';
const require=createRequire(new URL('../rayfin/functions/package.json',import.meta.url));
const sql=require('mssql');const {DefaultAzureCredential}=require('@azure/identity');
const {values}=parseArgs({options:{binding:{type:'string',default:'tools/binding.live.local.json'},
  plan:{type:'string'},'actor-sub':{type:'string'},batch:{type:'string',default:'0'}}});
if(!values.plan || !values['actor-sub'])throw new Error('--plan and existing --actor-sub required.');
const binding=JSON.parse(await readFile(values.binding,'utf8'));
const plan=JSON.parse(await readFile(values.plan,'utf8'));const profile=validateProfile(plan.profile);
const rows=parseCsv(await readFile(resolve(dirname(values.plan),plan.transactions_file),'utf8'));
if(digest(rows)!==plan.source_manifest_hash || binding.workspace_id!==plan.workspace_id ||
    binding.capacity_id!==plan.capacity_id || binding.database_item_id!==plan.database_item_id)
  throw new Error('Manifest or app binding changed.');
const run={profile,source_manifest_hash:plan.source_manifest_hash,policy_hash:plan.policy_hash,lease_id:randomUUID()};
if(runFingerprint(run)!==plan.fingerprint)throw new Error('Plan fingerprint mismatch.');
const token=await new DefaultAzureCredential({tenantId:binding.tenant_id}).getToken('https://database.windows.net/.default');
const pool=await poolFor(binding,token.token);
try{
  const before=await readRun(pool,profile.run_key);const index=Number(values.batch);
  if(!before.committed.includes(index))throw new Error('Replay is allowed only for an existing committed chunk.');
  const result=await pool.request().input('sub',sql.NVarChar(128),values['actor-sub'])
    .query('SELECT id,user_id,enabled,expires_at FROM dbo.OperatorGrants WHERE user_id=@sub');
  const grant=result.recordset[0];assertOperator(grant,new Date());
  const chunk=rows.slice(index*profile.batch_size,(index+1)*profile.batch_size);
  const first=await bulkSourceTransactions(pool,grant,run,index,chunk);
  const second=await bulkSourceTransactions(pool,grant,run,index,chunk);
  const after=await readRun(pool,profile.run_key);
  if(canonical(first)!==canonical(second) || before.run.committed_orders!==after.run.committed_orders ||
    before.run.committed_events!==after.run.committed_events || canonical(before.committed)!==canonical(after.committed))
    throw new Error('Replay altered the persisted checkpoint.');
  const facts=await pool.request().input('run',sql.NVarChar(128),profile.run_key)
    .query(`SELECT COUNT(*) AS events,COUNT(DISTINCT event_id) AS unique_events,
      SUM(CASE WHEN payload<>payload_json OR ISJSON(payload_json)<>1 THEN 1 ELSE 0 END) AS invalid_payloads
      FROM dbo.Outboxes WHERE run_id=@run;
      SELECT COUNT(DISTINCT JSON_VALUE(payload_json,'$.order_id')) AS created_orders
      FROM dbo.Outboxes WHERE run_id=@run AND event_type='rental.created';
      SELECT event_type,COUNT(*) AS count FROM dbo.Outboxes WHERE run_id=@run GROUP BY event_type;`);
  console.log(canonical({verified_replay:true,receipt:first,
    committed_orders:after.run.committed_orders,committed_events:after.run.committed_events,
    committed_batches:after.run.committed_batches,status:after.run.status,facts:facts.recordsets}));
}finally{await pool.close();}
