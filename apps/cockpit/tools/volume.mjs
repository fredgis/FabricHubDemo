/**
 * Trusted bounded volume profile. plan does not mutate SQL; execute requires
 * parent approval + a real existing operator grant. No source credentials,
 * frontend invocations, event-only generator, or capacity change.
 */
import { mkdir, readFile, rename, stat, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, isAbsolute, relative, resolve } from 'node:path';
import { randomUUID } from 'node:crypto';
import { parseArgs } from 'node:util';
import { fileURLToPath } from 'node:url';
import { assertOperator, canonical, offerPolicy } from '../rayfin/functions/dist/src/domain.js';
import { poolFor } from '../rayfin/functions/dist/src/storage.js';
import { bulkSourceTransactions, runFingerprint } from '../rayfin/functions/dist/src/volume-batch.js';
import { initializeRun, readRun, transitionRun } from '../rayfin/functions/dist/src/volume-runs.js';
import { digest, validateBatch, validateProfile, volumeEstimate } from '../rayfin/functions/dist/src/volume-domain.js';
import { parseCsv, csvText } from './lib/csv.mjs';
import { runChunks } from './lib/volume-runner.mjs';
import { assertVolumeApproval } from './lib/volume-approval.mjs';

const require = createRequire(new URL('../rayfin/functions/package.json', import.meta.url));
const sql = require('mssql');
const { DefaultAzureCredential } = require('@azure/identity');
const { values, positionals } = parseArgs({ allowPositionals:true, options: {
  binding:{type:'string',default:'tools/binding.live.local.json'},
  profile:{type:'string',default:'tools/volume.profile.json'},
  plan:{type:'string'}, transactions:{type:'string'}, approval:{type:'string'}, execute:{type:'boolean'},
  'actor-sub':{type:'string'}, rate:{type:'string',default:'10'}, concurrency:{type:'string',default:'1'},
  'max-seconds':{type:'string',default:'1800'}, 'max-pending-events':{type:'string',default:'20000'},
} });
const action = positionals[0];
if (!['plan','status','execute','cancel'].includes(action) || positionals.length !== 1)
  throw new Error('Usage: node tools/volume.mjs plan|status|execute|cancel [options].');
const stateRoot = resolve(dirname(fileURLToPath(import.meta.url)), 'volume-state');
function safeStatePath(path) {
  const absolute = resolve(path);
  const rel = relative(stateRoot, absolute);
  if (!rel || rel.startsWith('..') || isAbsolute(rel)) throw new Error('Volume state must remain under apps/cockpit/tools/volume-state/.');
  return absolute;
}
async function json(path) {
  if ((await stat(path)).size > 64*1024*1024) throw new Error('Input exceeds 64 MiB.');
  return JSON.parse(await readFile(path,'utf8'));
}
async function save(path, object) {
  safeStatePath(path);
  await mkdir(dirname(path),{recursive:true});
  const temporary = `${path}.${randomUUID()}.tmp`;
  await writeFile(temporary, canonical(object)+'\n', {encoding:'utf8',flag:'wx'});
  await rename(temporary,path);
}
async function sourceRows(path) {
  if ((await stat(path)).size > 64*1024*1024) throw new Error('Source CSV exceeds 64 MiB.');
  const rows = parseCsv(await readFile(path,'utf8'));
  const seen = new Set();
  for (const row of rows) {
    if (Object.keys(row).join(',') !== 'source_transaction_key,customer_key,offer_key')
      throw new Error('Source CSV columns must be source_transaction_key,customer_key,offer_key in that order.');
    if (seen.has(row.source_transaction_key)) throw new Error('Duplicate source transaction key in run manifest.');
    seen.add(row.source_transaction_key);
  }
  return rows;
}
async function sources(pool) {
  const result = await pool.request().query(`
    SELECT customer_key,territory FROM dbo.Customers ORDER BY customer_key;
    SELECT offer_key,content_key,territory,currency,transaction_type,price_minor,start_window_hours,play_window_hours
      FROM dbo.Offers WHERE transaction_type IN ('TVOD','EST') ORDER BY offer_key;
    SELECT content_key,duration_seconds,license,source_url,image_url FROM dbo.Contents ORDER BY content_key;`);
  return {customers:result.recordsets[0],offers:result.recordsets[1],content:result.recordsets[2]};
}
function policySnapshot(rows, source) {
  const customers = new Set(rows.map(row=>row.customer_key));
  const offers = new Set(rows.map(row=>row.offer_key));
  const selectedOffers = source.offers.filter(o=>offers.has(o.offer_key));
  const content = new Set(selectedOffers.map(o=>o.content_key));
  const selected = { customers:source.customers.filter(c=>customers.has(c.customer_key)),
    offers:selectedOffers,content:source.content.filter(c=>content.has(c.content_key)) };
  if (selected.customers.length!==customers.size || selected.offers.length!==offers.size || selected.content.length!==content.size)
    throw new Error('Run manifest references source rows not imported into this exact database.');
  const customerMap = new Map(selected.customers.map(c=>[c.customer_key,c]));
  const offerMap = new Map(selected.offers.map(o=>[o.offer_key,o]));
  for (const row of rows) if (customerMap.get(row.customer_key).territory !== offerMap.get(row.offer_key).territory)
    throw new Error('Source transaction territory does not match its persisted offer.');
  return selected;
}
function generate(profile, source) {
  source.offers.forEach(offerPolicy);
  const byTerritory = new Map();
  const eligibleContent=new Set(source.content.filter(c=>c.duration_seconds>=profile.progress_updates).map(c=>c.content_key));
  for (const o of source.offers) {
    if(!eligibleContent.has(o.content_key))continue;
    const key = `${o.territory}:${o.transaction_type}`;
    if (!byTerritory.has(key)) byTerritory.set(key,[]);
    byTerritory.get(key).push(o);
  }
  const customers = source.customers.filter(c=>byTerritory.has(`${c.territory}:TVOD`) &&
    (!profile.purchase_every || byTerritory.has(`${c.territory}:EST`)));
  if (!customers.length) throw new Error('No eligible actual CRM customers and persisted offers.');
  return Array.from({length:profile.total_orders},(_,index)=>{
    const customer=customers[index%customers.length];
    const type=profile.purchase_every && (index+1)%profile.purchase_every===0 ? 'EST':'TVOD';
    const offers=byTerritory.get(`${customer.territory}:${type}`);
    const offer=offers[(index+Math.floor(index/customers.length))%offers.length];
    return {source_transaction_key:`${profile.run_key}/${index}`,customer_key:customer.customer_key,offer_key:offer.offer_key};
  });
}
async function validateWorkspace(binding, credential) {
  const token=await credential.getToken('https://api.fabric.microsoft.com/.default');
  const response=await fetch(`https://api.fabric.microsoft.com/v1/workspaces/${binding.workspace_id}`,{
    headers:{Authorization:`Bearer ${token.token}`,'x-ms-fabric-skill':'rayfin'}});
  if (!response.ok) throw new Error(`Workspace validation failed (HTTP ${response.status}).`);
  const workspace=await response.json();
  if (workspace.displayName!=='MSFlix' || workspace.capacityId!==binding.capacity_id)
    throw new Error('Workspace or existing F16 capacity binding changed. No capacity reassignment is allowed.');
}
async function retrySameChunk(work) {
  for (let attempt=0;;attempt++) {
    try { return await work(); }
    catch(error) {
      const number=error.number??error.originalError?.info?.number;
      if (attempt>=2 || !([1205,40197,40501,40613].includes(number) ||
        ['ETIMEOUT','ESOCKET','ECONNRESET'].includes(error.code))) throw error;
      await new Promise(resolve=>setTimeout(resolve,500*2**attempt));
    }
  }
}

let pool;
let run;
let grant;
let acquired=false;
let stopping=false;
let approval;
const abort = () => { stopping=true; };
process.on('SIGINT',abort); process.on('SIGTERM',abort);
try {
  const binding=await json(values.binding);
  const credential=new DefaultAzureCredential({tenantId:binding.tenant_id});
  const token=await credential.getToken('https://database.windows.net/.default');
  pool=await poolFor(binding,token.token);
  if (action==='plan') {
    const profile=validateProfile(await json(values.profile));
    const source=await sources(pool);
    const rows=values.transactions ? await sourceRows(values.transactions) : generate(profile,source);
    if (rows.length!==profile.total_orders) throw new Error('Source row count does not match profile total_orders.');
    for (let i=0;i<volumeEstimate(profile).batches;i++)
      validateBatch(profile,i,rows.slice(i*profile.batch_size,(i+1)*profile.batch_size));
    const snapshot=policySnapshot(rows,source);
    if (snapshot.content.some(c=>c.duration_seconds<profile.progress_updates))
      throw new Error('Progress updates must be strictly increasing within actual film duration.');
    const contract={profile,source_manifest_hash:digest(rows),policy_hash:digest(snapshot)};
    const directory=safeStatePath(resolve(stateRoot,profile.run_key));
    await mkdir(directory,{recursive:true});
    const csvPath=resolve(directory,'transactions.csv');
    const text=csvText(['source_transaction_key','customer_key','offer_key'],rows);
    const proposed={...contract,fingerprint:runFingerprint(contract),expected:volumeEstimate(profile),
      workspace_id:binding.workspace_id,capacity_id:binding.capacity_id,database_item_id:binding.database_item_id,
      source_counts:{content:snapshot.content.length,customers:snapshot.customers.length,offers:snapshot.offers.length},
      generated_at:new Date().toISOString(),transactions_file:'transactions.csv',persisted_orders:false};
    const planPath=resolve(directory,'plan.json');
    // An existing frozen plan is never silently overwritten after source expansion.
    try {
      const previous=await json(planPath);
      if (previous.fingerprint!==proposed.fingerprint) throw new Error('Run key already has a different plan. Use a new run_key.');
    } catch(error) {if(error.code!=='ENOENT')throw error;}
    await writeFile(csvPath,text,'utf8');
    await save(planPath,proposed);
    console.log(canonical({plan:planPath,...proposed,requires_parent_approval:true}));
  } else {
    if (!values.plan) throw new Error('--plan is required for status/execute/cancel.');
    const planPath=safeStatePath(values.plan);
    const plan=await json(planPath);
    const profile=validateProfile(plan.profile);
    if (plan.workspace_id!==binding.workspace_id || plan.capacity_id!==binding.capacity_id ||
        plan.database_item_id!==binding.database_item_id) throw new Error('Plan is bound to a different app database/workspace/capacity.');
    const rows=await sourceRows(safeStatePath(resolve(dirname(planPath),plan.transactions_file)));
    if (rows.length!==profile.total_orders || digest(rows)!==plan.source_manifest_hash ||
        digest(policySnapshot(rows,await sources(pool)))!==plan.policy_hash)
      throw new Error('Source manifest or actual server policy changed. Refusing execution/resume.');
    run={profile,source_manifest_hash:plan.source_manifest_hash,policy_hash:plan.policy_hash,
      lease_id:randomUUID(),max_pending_events:Number(values['max-pending-events'])};
    if (runFingerprint(run)!==plan.fingerprint || canonical(plan.expected)!==canonical(volumeEstimate(profile)))
      throw new Error('Plan fingerprint or expected order/event bounds are invalid.');
    if (action==='status') {
      console.log(canonical(await readRun(pool,profile.run_key)));
    } else {
      if (!values['actor-sub']) throw new Error('--actor-sub must be an existing authorized worker grant; this tool never grants permission.');
      const result=await pool.request().input('sub',sql.NVarChar(128),values['actor-sub'])
        .query('SELECT id,user_id,enabled,expires_at FROM dbo.OperatorGrants WHERE user_id=@sub');
      grant=result.recordset[0]; assertOperator(grant,new Date());
      if (action==='cancel') {
        await transitionRun(pool,grant,run,'cancel');
        console.log(canonical({run_key:profile.run_key,cancellation_requested:true}));
      } else {
        if (!values.execute || !values.approval) throw new Error('Mass execution requires --execute AND an exact parent --approval file.');
        approval=await json(values.approval); assertVolumeApproval(approval,plan);
        await validateWorkspace(binding,credential);
        await initializeRun(pool,grant,run);
        const previous=await readRun(pool,profile.run_key);
        if (previous.run.status==='completed') {
          console.log(canonical({already_completed:true,...previous}));
        } else {
          await transitionRun(pool,grant,run,'acquire'); acquired=true;
          const checkpointPath=resolve(dirname(planPath),'checkpoint.json');
          const cancelPath=resolve(dirname(planPath),'CANCEL');
          let lastStatusCheck=-Infinity;
          let cancelled=false;
          const outcome=await runChunks({
            batches:volumeEstimate(profile).batches,batchSize:profile.batch_size,totalOrders:profile.total_orders,
            checkpoint:()=>readRun(pool,profile.run_key),
            execute:index=>{
              assertVolumeApproval(approval,plan);
              return retrySameChunk(()=>bulkSourceTransactions(pool,grant,run,index,
                rows.slice(index*profile.batch_size,(index+1)*profile.batch_size)));
            },
          },{
            concurrency:Number(values.concurrency),ordersPerSecond:Number(values.rate),maxSeconds:Number(values['max-seconds']),
            shouldStop:async()=>{
              if(stopping)return true;
              try {await stat(cancelPath);return true;} catch(error){if(error.code!=='ENOENT')throw error;}
              if(performance.now()-lastStatusCheck>=2000){
                const current=await readRun(pool,profile.run_key);
                cancelled=current.run.cancel_requested;lastStatusCheck=performance.now();
              }
              return cancelled;
            },
            onCheckpoint:async committed=>{
              const current=await readRun(pool,profile.run_key);
              await save(checkpointPath,{fingerprint:plan.fingerprint,committed,
                committed_orders:current.run.committed_orders,committed_events:current.run.committed_events,
                captured_at:new Date().toISOString(),source_of_truth:'SQL CommandReceipts + VolumeRuns'});
              console.log(canonical({run_key:profile.run_key,committed_orders:current.run.committed_orders,
                committed_events:current.run.committed_events,committed_batches:current.run.committed_batches}));
            },
          });
          const current=await readRun(pool,profile.run_key);
          if(!current.run.cancel_requested)await transitionRun(pool,grant,run,outcome.reason==='completed'?'complete':'pause');
          acquired=false;
          console.log(canonical({...outcome,...await readRun(pool,profile.run_key)}));
        }
      }
    }
  }
} catch(error) {
  if(acquired && pool && run && grant) {
    try {await transitionRun(pool,grant,run,'pause');} catch {/* lease may have expired or permission was revoked; SQL receipts remain authoritative */}
  }
  console.error(canonical({actual_volume_run:false,error:error.code??'VOLUME_FAILED',
    message:error.code && error.code!=='VOLUME_BACKLOG_LIMIT' ? 'Database/credential operation failed; inspect authorized telemetry.' :
      String(error.message).replace(/Bearer\s+\S+/gi,'Bearer [redacted]').replace(/eyJ[\w-]+\.[\w-]+\.[\w-]+/g,'[redacted]').slice(0,900)}));
  process.exitCode=1;
} finally {
  process.off('SIGINT',abort);process.off('SIGTERM',abort);
  if(pool)await pool.close();
}
