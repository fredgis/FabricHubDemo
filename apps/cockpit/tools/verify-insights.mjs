/** Read-only: existing cached credentials, aggregate evidence, no login, grants or deployment.
 * --mode baseline reads the existing dashboard; it does NOT verify the new backend.
 * --mode local executes the built backend and an independent SQL aggregate comparison.
 * --mode native invokes the deployed Insights function; add --compare-sql for that comparison.
 */
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import { parseArgs } from 'node:util';
import { RayfinClient } from '@microsoft/rayfin-client';
import { signInWithEntraToken } from '@microsoft/rayfin-auth-provider-fabric';
import { RayfinAuth } from '@microsoft/rayfin-cli/auth';
import { readGoldInsights, parseInsightsFilters } from '../rayfin/functions/dist/src/gold-insights.js';
import { goldPool, connectGoldPool } from '../rayfin/functions/dist/src/gold-dashboard.js';

const require = createRequire(new URL('../rayfin/functions/package.json', import.meta.url));
const sql = require('mssql');
const evidenceDirectory = new URL('../../../.state/insights/', import.meta.url);
const jsonFile = async url => JSON.parse(await readFile(url, 'utf8'));
const exact = value => {
  if (typeof value !== 'string' || !/^(0|[1-9]\d{0,37})$/.test(value)) throw new Error('INVALID_AGGREGATE');
  return value;
};
const sum = (rows, field) => rows.reduce((total, row) => total + BigInt(exact(row[field])), 0n).toString();
const requireCheck = (condition, code) => { if (!condition) throw new Error(code); };
const claimsOf = token => JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString('utf8'));

// Money is aggregated directly from order lines. EXISTS cannot multiply it by session or CRM rows.
export const COMPARISON_QUERY = `SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL SNAPSHOT;
BEGIN TRY
  BEGIN TRANSACTION;
  SELECT TOP (1) run_id,completed_at FROM gold.publication ORDER BY completed_at DESC,run_id;
  WITH selected AS (
    SELECT f.order_id,f.customer_key,f.content_key,f.amount_minor,f.first_play_at
    FROM gold.fact_order_line f
    WHERE f.created_at>=@date_from AND f.created_at<DATEADD(day,1,@date_to) AND f.currency=@currency
      AND (@territory='' OR COALESCE(NULLIF(f.territory,''),'Unknown')=@territory)
      AND (@transaction_type='' OR f.transaction_type=@transaction_type)
      AND (@genre='' OR EXISTS (SELECT 1 FROM gold.dim_content c WHERE c.content_key=f.content_key
        AND COALESCE(NULLIF(c.genre,''),'Unknown')=@genre))
  ), matched_sessions AS (
    SELECT p.order_id,p.status FROM gold.fact_playback_session p
    WHERE EXISTS (SELECT 1 FROM selected f WHERE f.order_id=p.order_id
      AND f.customer_key=p.customer_key AND f.content_key=p.content_key)
  )
  SELECT CONVERT(varchar(40),COUNT_BIG(DISTINCT order_id)) AS orders,
    CONVERT(varchar(40),COUNT_BIG(*)) AS orderLines,
    CONVERT(varchar(40),COUNT_BIG(DISTINCT customer_key)) AS customers,
    CONVERT(varchar(40),COUNT_BIG(DISTINCT content_key)) AS titles,
    CONVERT(varchar(40),COALESCE(SUM(CAST(amount_minor AS decimal(38,0))),0)) AS bookedMinor,
    CONVERT(varchar(40),(SELECT COUNT_BIG(*) FROM matched_sessions)) AS sessions,
    CONVERT(varchar(40),(SELECT COUNT_BIG(*) FROM matched_sessions WHERE UPPER(status)='COMPLETED')) AS completedSessions,
    CONVERT(varchar(40),(SELECT COUNT_BIG(*) FROM (
      SELECT order_id FROM selected WHERE first_play_at IS NOT NULL UNION SELECT order_id FROM matched_sessions
    ) played)) AS playedOrders FROM selected;
  SELECT TOP (33) currency,CONVERT(varchar(10),MIN(created_at),23) AS date_from,
    CONVERT(varchar(10),MAX(created_at),23) AS date_to,CONVERT(varchar(40),COUNT_BIG(*)) AS order_lines,
    CONVERT(varchar(40),SUM(CAST(amount_minor AS decimal(38,0)))) AS booked_minor
    FROM gold.fact_order_line GROUP BY currency ORDER BY currency;
  SELECT TOP (257) TABLE_NAME AS table_name,COLUMN_NAME AS column_name,DATA_TYPE AS data_type
    FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='gold' ORDER BY TABLE_NAME,ORDINAL_POSITION;
  SELECT TOP (33) purpose,channel,CONVERT(varchar(40),COUNT_BIG(*)) AS consent_rows
    FROM gold.fact_customer_consent GROUP BY purpose,channel ORDER BY purpose,channel;
  COMMIT TRANSACTION;
END TRY
BEGIN CATCH
  IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
  THROW;
END CATCH;`;

async function compareSql(binding, token, result) {
  const filters = parseInsightsFilters(JSON.stringify(result.filters));
  const pool = goldPool(binding, token);
  try {
    await connectGoldPool(pool);
    const { recordsets: sets } = await pool.request()
      .input('date_from', sql.Date, new Date(`${filters.from}T00:00:00Z`))
      .input('date_to', sql.Date, new Date(`${filters.to}T00:00:00Z`))
      .input('currency', sql.VarChar(3), filters.currency)
      .input('territory', sql.VarChar(64), filters.territory)
      .input('genre', sql.VarChar(128), filters.genre)
      .input('transaction_type', sql.VarChar(4), filters.transactionType).query(COMPARISON_QUERY);
    requireCheck(sets.length === 5 && sets[0].length === 1 && sets[1].length === 1
      && sets[2].length <= 32 && sets[3].length <= 256 && sets[4].length <= 32, 'COMPARISON_BOUNDARY');
    requireCheck(sets[0][0].run_id === result.freshness.publication_run_id, 'PUBLICATION_CHANGED_RETRY');
    for (const key of Object.keys(result.summary))
      requireCheck(exact(sets[1][0][key]) === String(result.summary[key]), 'AGGREGATE_MISMATCH');
    return { summary_matches: true, snapshot_run_id: sets[0][0].run_id,
      currency_extents: sets[2], gold_schema: sets[3], consent_purpose_channels: sets[4] };
  } finally { await pool.close(); }
}

export async function verifyInsights() {
  let client;
  let mode = 'local';
  let stage = 'arguments';
  const evidence = { verified_at: new Date().toISOString(), status: 'blocked', native_user_authenticated: false,
    new_backend_executed: false, independent_sql_compared: false };
  try {
    const { values } = parseArgs({ options: {
      mode: { type: 'string', default: 'local' }, filters: { type: 'string', default: '{}' },
      'compare-sql': { type: 'boolean', default: false }, 'sql-auth': { type: 'string', default: 'rayfin' },
    } });
    requireCheck(['local', 'native', 'baseline'].includes(values.mode), 'INVALID_MODE');
    requireCheck(['rayfin', 'azure-cli'].includes(values['sql-auth']), 'INVALID_SQL_AUTH');
    mode = values.mode;
    parseInsightsFilters(values.filters);
    stage = 'binding';
    const [operational, gold, registry] = await Promise.all([
      jsonFile(new URL('./binding.live.local.json', import.meta.url)),
      jsonFile(new URL('./gold.binding.live.local.json', import.meta.url)),
      jsonFile(new URL('../rayfin/.deployments.json', import.meta.url)),
    ]);
    const deployment = registry.deployments[registry.active];
    const api = new URL(deployment.fabricApiUrl);
    requireCheck(operational.verified === true && gold.verified === true
      && gold.binding_key === 'business-gold' && gold.name === 'MSFlixGold'
      && gold.workspace_id === operational.workspace_id && gold.capacity_id === operational.capacity_id
      && gold.sql_database === gold.item_id && gold.sql_server.endsWith('.datawarehouse.fabric.microsoft.com')
      && deployment.fabricWorkspaceId === operational.workspace_id && deployment.fabricItemId === operational.fabric_item_id
      && deployment.fabricTenantId === operational.tenant_id && api.protocol === 'https:'
      && api.hostname === `${operational.capacity_id.replaceAll('-', '')}.pbidedicated.windows.net`, 'BINDING_MISMATCH');
    evidence.source = { name: gold.name, workspace_id: gold.workspace_id, item_id: gold.item_id };
    stage = 'cached-fabric-credential';
    const auth = new RayfinAuth({ tenantId: operational.tenant_id });
    const cached = await auth.acquireToken(['https://analysis.windows.net/powerbi/api/Item.Execute.All'], { silentOnly: true });
    const entraToken = cached.accessToken ?? cached.token;
    const claims = claimsOf(entraToken);
    requireCheck(claims.tid === operational.tenant_id && claims.oid
      && (claims.scp ?? '').split(' ').includes('Item.Execute.All'), 'DELEGATED_IDENTITY_MISMATCH');
    client = new RayfinClient({ baseUrl: deployment.fabricApiUrl, publishableKey: deployment.publishableKey, authStorage: false });
    stage = 'native-authentication';
    const session = await signInWithEntraToken(client.auth, { entraToken });
    requireCheck(session.isAuthenticated && session.user?.id, 'NATIVE_AUTHENTICATION_FAILED');
    evidence.native_user_authenticated = true;

    if (mode === 'baseline') {
      stage = 'existing-dashboard-read';
      const dashboard = await client.functions.businessDashboard.invoke();
      requireCheck(dashboard.source.workspace_id === gold.workspace_id && dashboard.source.item_id === gold.item_id, 'SOURCE_MISMATCH');
      requireCheck(dashboard.commercial.length <= 96, 'BASELINE_BOUNDARY');
      evidence.baseline = { state: dashboard.state, freshness: dashboard.freshness, commercial: dashboard.commercial,
        dimensions: dashboard.dimensions, current_sessions: sum(dashboard.playback, 'current_sessions'),
        recorded_conversions: sum(dashboard.campaigns, 'recorded_conversions') };
      evidence.status = 'baseline-only';
      evidence.limitation = 'Existing published aggregates only; does not validate Insights SQL, live fact date extents or CRM purpose semantics.';
    } else {
      stage = 'caller-binding-read';
      const readable = await client.data.AnalyticsBinding.select(['id', 'workspace_id', 'capacity_id', 'item_id', 'verified'])
        .where({ binding_key: { eq: 'business-gold' } }).execute();
      requireCheck(readable.length === 1 && readable[0].verified && readable[0].id === gold.id
        && readable[0].item_id === gold.item_id && readable[0].workspace_id === gold.workspace_id
        && readable[0].capacity_id === gold.capacity_id, 'CALLER_BINDING_MISMATCH');
      let sqlToken;
      if (mode === 'local' || values['compare-sql']) {
        stage = 'cached-sql-credential';
        if (values['sql-auth'] === 'azure-cli') {
          const { AzureCliCredential } = require('@azure/identity');
          sqlToken = (await new AzureCliCredential({ tenantId: operational.tenant_id })
            .getToken('https://database.windows.net/.default')).token;
        } else {
          const token = await auth.acquireToken(['https://database.windows.net/.default'], { silentOnly: true });
          sqlToken = token.accessToken ?? token.token;
        }
        const sqlClaims = claimsOf(sqlToken);
        requireCheck(sqlClaims.tid === claims.tid && sqlClaims.oid === claims.oid
          && sqlClaims.aud?.replace(/\/$/, '') === 'https://database.windows.net', 'SQL_IDENTITY_MISMATCH');
      }
      stage = mode === 'native' ? 'native-insights-read' : 'local-insights-read';
      const result = mode === 'native'
        ? await client.functions.businessInsights.invoke({ filtersJson: values.filters })
        : await readGoldInsights(gold, sqlToken, values.filters);
      requireCheck(result.source.workspace_id === gold.workspace_id && result.source.item_id === gold.item_id, 'SOURCE_MISMATCH');
      evidence.new_backend_executed = true;
      evidence.insights = { state: result.state, freshness: result.freshness, filters: result.filters, options: result.options,
        scope: result.scope, summary: result.summary, audience: result.audience,
        result_sizes: { daily: result.daily.length, heatmap: result.heatmap.length, titles: result.titles.length, territories: result.territories.length },
        sources: result.sources };
      if (sqlToken && result.state !== 'unpublished') {
        stage = 'independent-sql-comparison';
        evidence.comparison = await compareSql(gold, sqlToken, result);
        evidence.independent_sql_compared = true;
      }
      evidence.status = result.state === 'unpublished' ? 'unpublished' : evidence.independent_sql_compared ? 'verified' : 'native-read-only';
    }
  } catch (error) {
    const known = ['INVALID_MODE', 'INVALID_SQL_AUTH', 'BINDING_MISMATCH', 'DELEGATED_IDENTITY_MISMATCH',
      'NATIVE_AUTHENTICATION_FAILED', 'SOURCE_MISMATCH', 'BASELINE_BOUNDARY', 'CALLER_BINDING_MISMATCH',
      'SQL_IDENTITY_MISMATCH', 'COMPARISON_BOUNDARY', 'PUBLICATION_CHANGED_RETRY', 'AGGREGATE_MISMATCH', 'INVALID_AGGREGATE'];
    evidence.failure = { stage, code: known.includes(error?.message) ? error.message : 'READ_ONLY_VERIFICATION_UNAVAILABLE' };
    if (stage === 'cached-sql-credential') evidence.limitation = 'No suitable existing SQL credential. No login, consent or permission change attempted.';
    process.exitCode = 1;
  } finally {
    client?.auth.destroy();
    await mkdir(evidenceDirectory, { recursive: true });
    const target = new URL(`${mode}-verification.json`, evidenceDirectory);
    await writeFile(target, JSON.stringify(evidence, null, 2));
    console.log(JSON.stringify({ ...evidence, evidence_file: fileURLToPath(target) }, null, 2));
  }
  return evidence;
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) await verifyInsights();
