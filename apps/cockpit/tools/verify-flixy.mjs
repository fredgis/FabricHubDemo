import { readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { randomUUID } from 'node:crypto';
import { parseArgs } from 'node:util';
import { RayfinClient } from '@microsoft/rayfin-client';
import { signInWithEntraToken } from '@microsoft/rayfin-auth-provider-fabric';
import { RayfinAuth } from '../node_modules/@microsoft/rayfin-cli/dist/auth/rayfin-auth.js';
import { parseFlixyVerificationAnswer } from './flixy-verification.mjs';

const { values } = parseArgs({ options: { 'initialize-access': { type: 'boolean' } } });
const tenant = '11111111-1111-4111-8111-111111111111';
const workspace = '33333333-3333-4333-8333-333333333333';
const app = '00000000-0000-4000-8000-000000100044';
const registry = JSON.parse(await readFile('rayfin/.deployments.json', 'utf8'));
const deployment = registry.deployments[registry.active];
const published = JSON.parse(await readFile('../../.state/flixy/published.json', 'utf8'));
if (deployment.fabricWorkspaceId !== workspace || deployment.fabricItemId !== app
  || published.workspace_id !== workspace || !published.published)
  throw new Error('Refusing Flixy invocation outside the qualified app and agent.');
const auth = new RayfinAuth({ tenantId: tenant });
const cached = await auth.acquireToken(
  ['https://analysis.windows.net/powerbi/api/Item.Execute.All'], { silentOnly: true });
const entraToken = cached.accessToken ?? cached.token;
const claims = JSON.parse(Buffer.from(entraToken.split('.')[1], 'base64url').toString());
if (claims.tid !== tenant || !claims.oid || !(claims.scp ?? '').split(' ').includes('Item.Execute.All'))
  throw new Error('The cached delegated identity is not qualified for the MSFlix app.');
const client = new RayfinClient({
  baseUrl: deployment.fabricApiUrl, publishableKey: deployment.publishableKey, authStorage: false,
});
try {
  const session = await signInWithEntraToken(client.auth, { entraToken });
  if (!session.isAuthenticated || !session.user?.id) throw new Error('Native user authentication failed.');
  if (values['initialize-access']) {
    const binding = JSON.parse(await readFile('tools/binding.live.local.json', 'utf8'));
    if (binding.tenant_id !== tenant || binding.workspace_id !== workspace
      || binding.fabric_item_id !== app || binding.verified !== true
      || !binding.sql_server.endsWith('.database.fabric.microsoft.com'))
      throw new Error('The app-linked SQL binding is not qualified.');
    const require = createRequire(new URL('../rayfin/functions/package.json', import.meta.url));
    const sql = require('mssql');
    const { AzureCliCredential } = require('@azure/identity');
    const credential = new AzureCliCredential({ tenantId: tenant });
    const sqlToken = await credential.getToken('https://database.windows.net/.default');
    const sqlClaims = JSON.parse(Buffer.from(sqlToken.token.split('.')[1], 'base64url').toString());
    if (sqlClaims.tid !== tenant || sqlClaims.oid !== claims.oid)
      throw new Error('SQL authoring identity differs from the authenticated app user.');
    const pool = new sql.ConnectionPool({
      server: binding.sql_server, database: binding.sql_database,
      options: { encrypt: true, trustServerCertificate: false },
      authentication: { type: 'azure-active-directory-access-token', options: { token: sqlToken.token } },
      connectionTimeout: 15000, requestTimeout: 30000, pool: { max: 1, min: 0 },
    });
    try {
      await pool.connect();
      const matched = await pool.request().input('id', sql.UniqueIdentifier, binding.id)
        .input('item', sql.NVarChar(128), app).input('workspace', sql.NVarChar(128), workspace)
        .query('SELECT id FROM dbo.RuntimeBindings WHERE id=@id AND fabric_item_id=@item AND workspace_id=@workspace AND verified=1');
      if (matched.recordset.length !== 1) throw new Error('Wrong native app database.');
      await pool.request().input('id', sql.UniqueIdentifier, randomUUID())
        .input('user', sql.NVarChar(128), session.user.id).input('oid', sql.NVarChar(36), claims.oid)
        .input('tenant', sql.NVarChar(36), tenant)
        .query(`IF EXISTS (SELECT 1 FROM dbo.FlixyAccessGrants WHERE user_id=@user)
          UPDATE dbo.FlixyAccessGrants SET entra_object_id=@oid,tenant_id=@tenant,enabled=1 WHERE user_id=@user
          ELSE INSERT dbo.FlixyAccessGrants(id,user_id,entra_object_id,tenant_id,enabled)
          VALUES (@id,@user,@oid,@tenant,1)`);
      await pool.request().input('id', sql.UniqueIdentifier, randomUUID())
        .input('url', sql.NVarChar(1000),
          `https://app.fabric.microsoft.com/groups/${workspace}/aiskills/${published.item_id}?ctid=${tenant}`)
        .input('description', sql.NVarChar(400),
          'Native read-only Data Agent: Gold and the ontology native graph. Administrator-approved callers; shared app-owner resource identity.')
        .query(`IF EXISTS (SELECT 1 FROM dbo.IntegrationLinks WHERE link_key='flixy-data-agent')
          UPDATE dbo.IntegrationLinks SET name='Flixy',type='DataAgent',url=@url,description=@description
          WHERE link_key='flixy-data-agent'
          ELSE INSERT dbo.IntegrationLinks(id,link_key,name,type,url,description)
          VALUES (@id,'flixy-data-agent','Flixy','DataAgent',@url,@description)`);
      console.log(JSON.stringify({ access: 'Current authenticated user only', app_binding_verified: true }));
    } finally {
      await pool.close();
    }
  }
  const pages = await client.functions.businessViews.invoke();
  if (pages.dashboard.state !== 'ready') throw new Error('Authoritative Gold snapshot is unavailable.');
  const expected = {
    films: pages.catalog.length, clients: pages.customers.length,
    commandes_distinctes: Number(pages.dashboard.freshness.order_lines),
  };
  const question = 'Dans MSFlixGold, combien de films, clients et commandes distinctes sont publies dans la derniere publication ? '
    + 'Reponds uniquement avec un objet JSON, sans Markdown: {"films":nombre,"clients":nombre,'
    + '"commandes_distinctes":nombre,"publication_utc":"date","sources":["tables utilisees"]}.';
  const first = await client.functions.flixyAsk.invoke({ question, historyJson: '[]' }, { timeoutMs: 200000 });
  if (!first.text?.trim() || !Array.isArray(first.sources)) throw new Error('Native Flixy response is invalid.');
  const counts = parseFlixyVerificationAnswer(first.text);
  for (const key of Object.keys(expected)) {
    if (!Number.isSafeInteger(counts[key]) || counts[key] !== expected[key])
      throw new Error(`Native Flixy ${key} differs from the independently read Gold snapshot.`);
  }
  if (!Array.isArray(counts.sources) || !counts.sources.includes('gold.fact_order_line')
    || !counts.publication_utc) throw new Error('Native Flixy omitted the requested source/freshness evidence.');
  console.log(JSON.stringify({ function: 'flixyAsk', answer: first }));
  const second = await client.functions.flixyAsk.invoke({
    question: "Utilise uniquement le graphe natif de l'ontologie MSFlixBusiness, pas SQL: montre un chemin reel client -> commande -> offre -> film, limite a un exemple. Indique les identifiants et la requete GQL utilisee.",
    historyJson: '[]',
  }, { timeoutMs: 200000 });
  if (!second.text?.trim()) throw new Error('Native Flixy graph response is empty.');
  console.log(JSON.stringify({ function: 'flixyAsk', graph_answer: second }));
  await writeFile('../../.state/flixy/cockpit-native-readback.json', JSON.stringify({
    native_user_authenticated: true, data_agent_id: published.item_id,
    verified_at: new Date().toISOString(), expected_gold_counts: expected,
    gold_counts_match: true, gold_answer: first, graph_answer: second,
  }, null, 2));
} finally {
  client.auth.destroy();
}
