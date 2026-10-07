/**
 * Trusted authoring hook, NOT shipped to the browser or exposed as a UDF.
 * Uses the current Azure credential chain. Never accepts source credentials.
 * Requires an exact, independently verified app-linked SQL binding JSON.
 */
import { readFile, stat } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { randomUUID } from 'node:crypto';
import { parseArgs } from 'node:util';
import { canonical, offerPolicy } from '../rayfin/functions/dist/src/domain.js';
import { parseCsv } from './lib/csv.mjs';
import { upsertChunk } from './lib/import-batch.mjs';

const require = createRequire(new URL('../rayfin/functions/package.json', import.meta.url));
const sql = require('mssql');
const { DefaultAzureCredential } = require('@azure/identity');
const { values } = parseArgs({ options: {
  binding: { type: 'string' }, catalog: { type: 'string' }, customers: { type: 'string' },
  offers: { type: 'string' }, campaigns: { type: 'string' }, members: { type: 'string' },
  'offer-policy': { type: 'string' },
  links: { type: 'string' }, 'initialize-binding': { type: 'boolean' },
  'operator-sub': { type: 'string' }, 'operator-hours': { type: 'string', default: '8' },
  'chunk-size': { type: 'string', default: '100' }, 'dry-run': { type: 'boolean' },
} });
const chunkSize = Number(values['chunk-size']);
if (!Number.isInteger(chunkSize) || chunkSize < 1 || chunkSize > 1000) throw new Error('Import chunk size must be 1-1000.');
if (values['dry-run'] && (values['initialize-binding'] || values['operator-sub']))
  throw new Error('Dry-run cannot initialize a binding or grant an operator.');
if (!values.binding) throw new Error('--binding must identify the verified app-linked SQL deployment.');
const binding = JSON.parse(await readFile(values.binding, 'utf8'));
for (const field of ['id', 'sql_server', 'sql_database', 'fabric_item_id', 'database_item_id', 'workspace_id', 'capacity_id', 'tenant_id'])
  if (typeof binding[field] !== 'string' || !binding[field]) throw new Error(`Binding requires ${field}.`);
if (binding.verified !== true || binding.binding_key !== 'app-linked-operational'
  || !binding.sql_server.endsWith('.database.fabric.microsoft.com'))
  throw new Error('Refusing an unverified or non-Fabric operational binding.');
const credentials = new DefaultAzureCredential({ tenantId: binding.tenant_id });
const token = await credentials.getToken('https://database.windows.net/.default');
const pool = new sql.ConnectionPool({ server: binding.sql_server, database: binding.sql_database,
  options: { encrypt: true, trustServerCertificate: false, abortTransactionOnError: true },
  authentication: { type: 'azure-active-directory-access-token', options: { token: token.token } },
  connectionTimeout: 15000, requestTimeout: 30000, pool: { max: 2, min: 0 },
});

const definitions = {
  Content: { key: 'content_key', event: 'content.upserted', fields: ['content_key','title','release_date','duration_seconds','genre','image_url','source_url','license','attribution',
    'metadata_license','metadata_date_precision','artwork_available','artwork_license','artwork_source_url','artwork_author'] },
  Customer: { key: 'customer_key', event: 'customer.upserted', fields: ['customer_key','name','territory'] },
  Offer: { key: 'offer_key', event: 'offer.upserted', fields: ['offer_key','content_key','territory','currency','transaction_type','price_minor','start_window_hours','play_window_hours'] },
  Campaign: { key: 'campaign_key', fields: ['campaign_key','name','status','type','start_date','end_date'] },
  CampaignMember: { key: 'member_key', fields: ['member_key','campaign_key','customer_key','status'] },
  IntegrationLink: { key: 'link_key', fields: ['link_key','name','type','url','description'] },
};
const lengths = { content_key:128, customer_key:128, offer_key:128, campaign_key:128, member_key:128,
  link_key:128, title:240, name:240, territory:16, currency:3, transaction_type:16, genre:80,
  image_url:1000, source_url:1000, license:160, attribution:1000, status:40, type:80, url:1000, description:400,
  metadata_license:160,metadata_date_precision:40,artwork_license:160,artwork_source_url:1000,artwork_author:1000 };
const optional = new Set(['start_date', 'end_date','metadata_license','metadata_date_precision','artwork_available',
  'artwork_license','artwork_source_url','artwork_author']);
function validate(table, row) {
  for (const field of definitions[table].fields) {
    const value = row[field];
    if (optional.has(field) && value == null) continue;
    if (field==='artwork_available') {
      if(typeof value!=='boolean')throw new Error('artwork_available must be a boolean.');
    } else if (['release_date', 'start_date', 'end_date'].includes(field)) {
      if (!Number.isFinite(Date.parse(value))) throw new Error(`${table}.${field} requires an actual date.`);
    } else if (['duration_seconds','price_minor','start_window_hours','play_window_hours'].includes(field)) {
      if (!Number.isSafeInteger(value) || value < 0 || value > 2147483647) throw new Error(`${table}.${field} must be an integer.`);
    } else if (typeof value !== 'string' || !value.length || value.length > lengths[field]) {
      throw new Error(`${table}.${field} is missing or exceeds its declared length.`);
    }
  }
  if (table === 'Content') {
    if(new URL(row.source_url).protocol!=='https:')throw new Error('Catalog sources require HTTPS.');
    const placeholder=row.image_url==='/catalog-unavailable.svg';
    if(!placeholder && new URL(row.image_url).protocol!=='https:')throw new Error('Artwork must be HTTPS or the owned unavailable asset.');
    const allowed=lic=>/^(CC BY(?:-SA)? [1-4]\.\d(?: [a-z]{2})?|CC0(?: 1\.0)?|Public domain)$/i.test(lic);
    if(!allowed(row.metadata_license??row.license))throw new Error('Explicit metadata license is required.');
    if(row.artwork_available===false && !placeholder)throw new Error('Unavailable artwork must use the owned unavailable asset.');
    if(placeholder && row.artwork_available!==false)throw new Error('Unavailable asset must be labelled artwork_available=false.');
    if(!placeholder && !allowed(row.artwork_license??row.license))throw new Error('Verified reusable artwork license is required; ND is excluded.');
    if (row.duration_seconds <= 0) throw new Error('Film duration must be positive.');
  }
  if (table === 'Offer') {
    if (row.transaction_type === 'SVOD') {
      if (!/^[A-Z]{3}$/.test(row.currency)) throw new Error('Invalid currency.');
    } else offerPolicy(row);
  }
  if (table === 'IntegrationLink' && new URL(row.url).protocol !== 'https:') throw new Error('Resource links require HTTPS.');
}
async function rows(path, property) {
  if ((await stat(path)).size > 64*1024*1024) throw new Error('Import file exceeds 64 MiB.');
  const text = await readFile(path, 'utf8');
  let result;
  if (path.toLowerCase().endsWith('.csv')) {
    const numeric = new Set(['duration_seconds','price_minor','start_window_hours','play_window_hours']);
    result = parseCsv(text).map(row => Object.fromEntries(Object.entries(row).map(([field,value]) => {
      if (numeric.has(field)) {
        if (!/^\d+$/.test(value)) throw new Error(`CSV ${field} must be an integer, not a decimal price.`);
        return [field, Number(value)];
      }
      if(field==='artwork_available'){
        if(value==='')return [field,null];
        if(!['true','false'].includes(value.toLowerCase()))throw new Error('CSV artwork_available must be true/false.');
        return [field,value.toLowerCase()==='true'];
      }
      return [field, optional.has(field) && value === '' ? null : value];
    })));
  } else {
    const json = JSON.parse(text);
    result = Array.isArray(json) ? json : json[property] ?? json.records;
  }
  if (!Array.isArray(result)) throw new Error(`Export must be an array or have ${property}/records array.`);
  if (result.length > 100000) throw new Error('Import is bounded at 100,000 records per file.');
  return result;
}

try {
  await pool.connect();
  const required = Object.keys(definitions).map(t => `${t}s`).concat(['Rentals','Playbacks','Outboxes','ControlCommands',
    'RuntimeBindings','OperatorGrants','CommandReceipts','EventSequences']);
  const tables = await pool.request().query("SELECT name FROM sys.tables WHERE schema_id=SCHEMA_ID('dbo')");
  const names = new Set(tables.recordset.map(r => r.name));
  if (required.some(name => !names.has(name))) throw new Error('Wrong database or decorated schema is not applied.');
  if (values['initialize-binding']) {
    const migration = await readFile(new URL('../rayfin/sql/operational.sql', import.meta.url), 'utf8');
    await pool.request().batch(migration);
    const fields = ['binding_key','sql_server','sql_database','fabric_item_id','workspace_id','capacity_id'];
    const req = pool.request().input('id', sql.UniqueIdentifier, binding.id);
    fields.forEach((field, i) => req.input(`p${i}`, sql.NVarChar(field === 'sql_server' ? 300 : field === 'sql_database' ? 200 : 128), binding[field]));
    await req.query(`IF NOT EXISTS (SELECT 1 FROM dbo.RuntimeBindings WHERE binding_key=@p0)
      INSERT dbo.RuntimeBindings (id,${fields.join(',')},verified) VALUES (@id,${fields.map((_, i) => `@p${i}`).join(',')},1)`);
  }
  const verified = await pool.request().input('id', sql.UniqueIdentifier, binding.id)
    .input('item', sql.NVarChar(128), binding.fabric_item_id).input('workspace', sql.NVarChar(128), binding.workspace_id)
    .input('capacity', sql.NVarChar(128), binding.capacity_id)
    .query('SELECT id FROM dbo.RuntimeBindings WHERE id=@id AND fabric_item_id=@item AND workspace_id=@workspace AND capacity_id=@capacity AND verified=1');
  if (verified.recordset.length !== 1) throw new Error('Database does not contain the exact app/workspace/capacity binding.');
  if (values['operator-sub']) {
    const hours = Number(values['operator-hours']);
    if (!Number.isInteger(hours) || hours < 1 || hours > 24) throw new Error('Operator grant must last 1-24 hours.');
    await pool.request().input('sub', sql.NVarChar(128), values['operator-sub'])
      .input('expires', sql.DateTime2, new Date(Date.now() + hours * 3600000)).input('id', sql.UniqueIdentifier, randomUUID())
      .query(`IF EXISTS (SELECT 1 FROM dbo.OperatorGrants WHERE user_id=@sub)
        UPDATE dbo.OperatorGrants SET enabled=1,expires_at=@expires WHERE user_id=@sub
        ELSE INSERT dbo.OperatorGrants(id,user_id,enabled,expires_at) VALUES (@id,@sub,1,@expires)`);
  }
  const datasets = [
    ['Content','catalog','content'], ['Customer','customers','customers'], ['Offer','offers','offers'],
    ['Campaign','campaigns','campaigns'], ['CampaignMember','members','members'], ['IntegrationLink','links','links'],
  ];
  const counts = {};
  for (const [table, option, property] of datasets) {
    if (!values[option] && !(table === 'Offer' && values['offer-policy'])) continue;
    let raw;
    if (table === 'Offer' && values['offer-policy']) {
      if (values.offers) throw new Error('Supply either --offers or --offer-policy, not both.');
      const policy = JSON.parse(await readFile(values['offer-policy'], 'utf8'));
      if (!Array.isArray(policy.territories) || policy.territories.length > 50) throw new Error('Invalid bounded offer policy.');
      const films = await pool.request().query('SELECT content_key FROM dbo.Contents ORDER BY content_key');
      raw = films.recordset.flatMap(f => policy.territories.flatMap(t => [
        { offer_key: `${f.content_key}:${t.territory}:RENTAL`, content_key: f.content_key,
          territory: t.territory, currency: t.currency, transaction_type: 'TVOD',
          price_minor: t.rental_minor, start_window_hours: policy.start_window_hours, play_window_hours: policy.play_window_hours },
        { offer_key: `${f.content_key}:${t.territory}:PURCHASE`, content_key: f.content_key,
          territory: t.territory, currency: t.currency, transaction_type: 'EST',
          price_minor: t.purchase_minor, start_window_hours: 0, play_window_hours: 0 },
      ]));
    } else raw = await rows(values[option], property);
    const records = raw.map(row => {
      if(table==='Content')return {...row,metadata_license:row.metadata_license??row.license,
        metadata_date_precision:row.metadata_date_precision??'source-reported',
        artwork_available:row.artwork_available??row.image_url!=='/catalog-unavailable.svg',
        artwork_license:row.artwork_license??(row.image_url==='/catalog-unavailable.svg'?null:row.license),
        artwork_source_url:row.artwork_source_url??(row.image_url==='/catalog-unavailable.svg'?null:row.source_url),
        artwork_author:row.artwork_author||null};
      if (table === 'Customer' && row.MSFlix_Key__c) return {
        customer_key: row.MSFlix_Key__c,
        name: [row.FirstName, row.LastName].filter(Boolean).join(' '),
        territory: row.MSFlix_Territory__c,
      };
      if (table === 'Campaign' && row.MSFlix_Key__c) return {
        campaign_key: row.MSFlix_Key__c, name: row.Name,
        status: row.Status ?? 'not_exported', type: row.Type ?? row.MSFlix_Channel__c,
        start_date: row.StartDate ?? null, end_date: row.EndDate ?? null,
      };
      return row;
    });
    const seen = new Set();
    for (const row of records) {
      validate(table, row);
      const natural = row[definitions[table].key];
      if (seen.has(natural)) throw new Error(`Duplicate ${table} natural key in import.`);
      seen.add(natural);
    }
    if (values['dry-run']) { counts[table] = { validated: records.length, persisted: false }; continue; }
    let changed = 0;
    const importRun = randomUUID();
    for (let offset = 0; offset < records.length; offset += chunkSize) {
      const tx = new sql.Transaction(pool);
      await tx.begin(sql.ISOLATION_LEVEL.SERIALIZABLE);
      const store = { tx, now: new Date(), runId: importRun, correlationId: `import:${importRun}:${offset}` };
      try {
        const chunkChanged=await upsertChunk(store,table,definitions[table],records.slice(offset,offset+chunkSize),lengths);
        await tx.commit(); changed += chunkChanged;
        console.log(canonical({ import_run: importRun, entity: table, committed_rows: Math.min(offset+chunkSize,records.length),
          changed, total_rows: records.length }));
      } catch (error) { try { await tx.rollback(); } catch { /* already rolled back */ } throw error; }
    }
    counts[table] = { read: records.length, changed };
  }
  console.log(canonical({ binding_verified: true, imports: counts }));
} catch (error) {
  // SQL driver errors may contain credentials/endpoints; report only a safe code.
  if (error?.code) throw new Error(`SQL import failed (${error.code}). Inspect server telemetry with your authorized identity.`);
  throw error;
} finally { await pool.close(); }
