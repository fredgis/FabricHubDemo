/**
 * Real SDK verification. Tokens stay in memory. No raw GraphQL or runtime
 * token copying to source, logs or local settings.
 * Default: read/health only. --exercise records one real rental and playback.
 */
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { parseArgs } from 'node:util';
import { randomUUID } from 'node:crypto';
import { RayfinClient } from '@microsoft/rayfin-client';
import { signInWithEntraToken } from '@microsoft/rayfin-auth-provider-fabric';
import { canonical } from '../rayfin/functions/dist/src/domain.js';
const require = createRequire(new URL('../rayfin/functions/package.json', import.meta.url));
const { DefaultAzureCredential } = require('@azure/identity');
const sql = require('mssql');
const { values } = parseArgs({ options: { exercise: { type: 'boolean' },
  'grant-operator': { type: 'boolean' }, 'expected-admin-email': { type: 'string' },
  'entra-token-stdin': { type: 'boolean' },
  binding: { type: 'string', default: 'tools/binding.live.local.json' } } });
const b = JSON.parse(await readFile(values.binding, 'utf8'));
const deployments = JSON.parse(await readFile(new URL('../rayfin/.deployments.json', import.meta.url), 'utf8'));
const d = deployments.deployments[deployments.active];
if (d.fabricWorkspaceId !== b.workspace_id || d.fabricItemId !== b.fabric_item_id)
  throw new Error('Active deployment does not match operational binding.');
const credential = new DefaultAzureCredential({ tenantId: b.tenant_id });
const client = new RayfinClient({ baseUrl: d.fabricApiUrl, publishableKey: d.publishableKey,
  authStorage: false });
try {
  let entraToken;
  if (values['entra-token-stdin']) {
    const chunks = [];
    for await (const chunk of process.stdin) chunks.push(chunk);
    entraToken = Buffer.concat(chunks).toString('utf8').trim();
  } else {
    entraToken = (await credential.getToken('https://analysis.windows.net/powerbi/api/.default')).token;
    const claims = JSON.parse(Buffer.from(entraToken.split('.')[1], 'base64url').toString());
    if (!(claims.scp ?? '').split(' ').includes('Item.Execute.All'))
      throw new Error('Cached Azure CLI token lacks Item.Execute.All. Narrow scope acquisition returned AADSTS65002 (Microsoft first-party preauthorization), not a tenant-admin permission failure. Use the Fabric portal broker or an approved delegated app token via --entra-token-stdin. No global Tenant.ReadWrite consent or login retry is required.');
  }
  const session = await signInWithEntraToken(client.auth, { entraToken });
  if (!session.isAuthenticated || !session.user) throw new Error('No actual Rayfin session established.');
  if (values['grant-operator']) {
    if (!values['expected-admin-email'] || session.user.email !== values['expected-admin-email'])
      throw new Error('Explicit expected admin identity is required for a bounded operator grant.');
    const token = await credential.getToken('https://database.windows.net/.default');
    const pool = new sql.ConnectionPool({ server:b.sql_server,database:b.sql_database,
      options:{encrypt:true,trustServerCertificate:false},
      authentication:{type:'azure-active-directory-access-token',options:{token:token.token}} });
    try {
      await pool.connect();
      await pool.request().input('sub', sql.NVarChar(128), session.user.id)
        .input('expires', sql.DateTime2, new Date(Date.now() + 3600000)).input('id', sql.UniqueIdentifier, randomUUID())
        .query(`IF EXISTS (SELECT 1 FROM dbo.OperatorGrants WHERE user_id=@sub)
          UPDATE dbo.OperatorGrants SET enabled=1,expires_at=@expires WHERE user_id=@sub
          ELSE INSERT dbo.OperatorGrants(id,user_id,enabled,expires_at) VALUES (@id,@sub,1,@expires)`);
    } finally { await pool.close(); }
  }
  const films = await client.data.Content.select(['content_key','title','image_url','license','attribution']).execute();
  const customers = await client.data.Customer.select(['customer_key','territory']).first(500).execute();
  const offers = await client.data.Offer.select(['offer_key','content_key','territory','transaction_type']).first(500).execute();
  const capabilities = await client.functions.capabilities.invoke();
  const health = await client.functions.health.invoke();
  console.log(JSON.stringify({ actual_session: true, films: films.length, customers: customers.length,
    offers: offers.length, capabilities, health }));
  if (values.exercise) {
    if (!capabilities.can_operate) throw new Error('No operator grant; refusing mutation.');
    const selected = offers.find(o => o.transaction_type === 'TVOD' && customers.some(c => c.territory === o.territory));
    const customer = customers.find(c => c.territory === selected?.territory);
    if (!selected || !customer) throw new Error('No real customer/TVOD offer pair imported.');
    const id = randomUUID();
    const input = { customer_key: customer.customer_key, offer_key: selected.offer_key, idempotency_key: id };
    const first = await client.functions.placeOrder.invoke({ input });
    const replay = await client.functions.placeOrder.invoke({ input });
    if (canonical(first) !== canonical(replay)) throw new Error('Idempotent replay returned a different receipt.');
    const playInput = { order_id: first.entity_key, idempotency_key: randomUUID() };
    const playback = await client.functions.startPlayback.invoke({ input: playInput });
    const playbackReplay = await client.functions.startPlayback.invoke({ input: playInput });
    if (canonical(playback) !== canonical(playbackReplay)) throw new Error('Playback replay changed.');
    const persisted = await client.data.Rental.select(['order_id','status','amount_minor','currency','first_play_at','expires_at'])
      .where({ order_id: { eq: first.entity_key } }).execute();
    const events = await client.data.Outbox.select(['event_id','entity_key','event_type','published_at'])
      .where({ correlation_id: { eq: id } }).execute();
    if (persisted.length !== 1 || events.length !== 1) throw new Error('Real mutation persistence or event cardinality is incorrect.');
    console.log(JSON.stringify({ real_scenario: true, first, replay, playback, persisted, committed_events: events }));
  }
} catch (error) {
  console.error(JSON.stringify({ verified: false, error: error?.code ?? 'RUNTIME_VERIFICATION_FAILED',
    message: String(error?.message ?? 'Unknown error').replace(/eyJ[\w-]+\.[\w-]+\.[\w-]+/g, '[redacted]').slice(0, 700) }));
  process.exitCode = 1;
} finally { client.auth.destroy(); }
