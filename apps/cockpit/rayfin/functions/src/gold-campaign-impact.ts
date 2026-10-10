import sql from 'mssql';
import type { AnalyticsBinding } from '../../data/schema.js';
import { connectGoldPool, goldPool } from './gold-dashboard.js';
import type { CampaignImpact, CampaignImpactFilters, CampaignImpactMetrics } from './gold-campaign-contract.js';

const DAY_MS = 86_400_000;
const UNAVAILABLE = 'Campaign Impact is unavailable. Verify the Gold view and app-identity SELECT access. No operational fallback.';
const INVALID = 'Campaign Impact failed a Gold integrity or result-boundary check. No partial totals are presented.';
export const CAMPAIGN_LIMITS = { days: 366, campaigns: 200, currencies: 32, territories: 64, titles: 12 } as const;

function date(value: unknown): string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value < '1000-01-01' || value > '9998-12-31')
    throw new Error('Use ISO dates in YYYY-MM-DD form.');
  const parsed = new Date(`${value}T00:00:00.000Z`);
  if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value)
    throw new Error('Use a real calendar date.');
  return value;
}
function dateRange(from: string, to: string): void {
  const days = (Date.parse(to) - Date.parse(from)) / DAY_MS + 1;
  if (days < 1 || days > CAMPAIGN_LIMITS.days) throw new Error('Select an ordered date range of at most 366 days.');
}

export function parseCampaignFilters(json: string): CampaignImpactFilters {
  if (typeof json !== 'string' || json.length > 2048) throw new Error('Campaign filters must be a small JSON object.');
  let value: unknown;
  try { value = JSON.parse(json); } catch { throw new Error('Campaign filters must be valid JSON.'); }
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Campaign filters must be a JSON object.');
  const input = value as Record<string, unknown>;
  if (Object.keys(input).some(key => !['from', 'to', 'territory', 'campaignKey', 'currency'].includes(key)))
    throw new Error('Unsupported Campaign Impact filter.');
  const field = (key: string, max: number): string => {
    const v = input[key] === undefined ? '' : input[key];
    if (typeof v !== 'string' || v.length > max || /[\u0000-\u001f\u007f]/.test(v)) throw new Error('Invalid campaign filter value.');
    return v;
  };
  const from = field('from', 10), to = field('to', 10), currency = field('currency', 3);
  if (from) date(from);
  if (to) date(to);
  if (from && to) dateRange(from, to);
  if (currency && !/^[A-Z]{3}$/.test(currency)) throw new Error('Select one uppercase three-letter currency. Currencies are not combined.');
  return { from, to, currency, territory: field('territory', 64), campaignKey: field('campaignKey', 128) };
}

const COHORT = `WITH cohort AS (
  SELECT v.* FROM gold.campaign_engaged_revenue v
  WHERE v.cohort_date BETWEEN @StartDate AND @EndDate
    AND (v.record_kind='contact' OR (v.attribution_status='recorded' AND v.currency=@SelectedCurrency))
    AND (@territory='' OR v.territory=@territory)
    AND (@campaign_key='' OR v.campaign_key=@campaign_key)
)`;
const METRICS = `
  COUNT_BIG(DISTINCT CASE WHEN record_kind='contact' THEN customer_key END) AS contacted_customers,
  COALESCE(SUM(touches),0) AS touches,
  COUNT_BIG(DISTINCT CASE WHEN record_kind='order' THEN customer_key END) AS buyers,
  COUNT_BIG(DISTINCT order_id) AS orders,
  COUNT_BIG(DISTINCT CASE WHEN played=1 THEN order_id END) AS played_orders,
  COUNT_BIG(DISTINCT CASE WHEN engaged=1 THEN order_id END) AS engaged_orders,
  COUNT_BIG(DISTINCT CASE WHEN unknown_duration=1 THEN order_id END) AS unknown_duration_orders,
  CONVERT(varchar(40),COALESCE(SUM(CAST(amount_minor AS decimal(38,0))),0)) AS booked_minor,
  CONVERT(varchar(40),COALESCE(SUM(CASE WHEN engaged=1 THEN CAST(amount_minor AS decimal(38,0)) ELSE 0 END),0)) AS engaged_minor,
  CONVERT(varchar(40),COALESCE(SUM(CASE WHEN record_kind='order' AND played=0 THEN CAST(amount_minor AS decimal(38,0)) ELSE 0 END),0)) AS not_started_minor`;

export const GOLD_CAMPAIGN_QUERY = `SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL SNAPSHOT;
BEGIN TRY
  BEGIN TRANSACTION;
  DECLARE @Run varchar(128), @PublishedAt datetime2(6), @MinimumDate date, @MaximumDate date;
  DECLARE @StartDate date=@from_date, @EndDate date=@to_date, @SelectedCurrency varchar(3)=NULLIF(@currency,'');
  SELECT TOP (1) @Run=run_id, @PublishedAt=completed_at FROM gold.publication ORDER BY completed_at DESC,run_id;
  IF @Run IS NOT NULL
  BEGIN
    SELECT @MinimumDate=MIN(report_date), @MaximumDate=MAX(report_date) FROM (
      SELECT CAST(MIN(occurred_at) AS date) AS report_date FROM gold.fact_campaign_touch GROUP BY campaign_key,customer_key
      UNION ALL SELECT CAST(created_at AS date) FROM gold.fact_order_line
    ) dates;
    IF @SelectedCurrency IS NULL
      SELECT TOP (1) @SelectedCurrency=currency FROM gold.fact_order_line GROUP BY currency ORDER BY COUNT_BIG(*) DESC,currency;
    IF @SelectedCurrency IS NULL SELECT TOP (1) @SelectedCurrency=currency FROM gold.currency ORDER BY currency;
  END;
  IF @StartDate IS NOT NULL AND @EndDate IS NULL
    SET @EndDate=CASE WHEN @MaximumDate BETWEEN @StartDate AND DATEADD(day,29,@StartDate) THEN @MaximumDate ELSE DATEADD(day,29,@StartDate) END;
  IF @EndDate IS NULL SET @EndDate=COALESCE(@MaximumDate,CAST(@query_time AS date));
  IF @StartDate IS NULL
    SET @StartDate=CASE WHEN @MinimumDate BETWEEN DATEADD(day,-29,@EndDate) AND @EndDate THEN @MinimumDate ELSE DATEADD(day,-29,@EndDate) END;
  IF @StartDate>@EndDate OR DATEDIFF(day,@StartDate,@EndDate)>=366 THROW 51020, 'Invalid campaign date range', 1;
  SELECT @Run AS run_id, @PublishedAt AS completed_at, @query_time AS queried_at,
    CONVERT(varchar(10),@StartDate,23) AS date_from, CONVERT(varchar(10),@EndDate,23) AS date_to,
    COALESCE(@SelectedCurrency,'') AS currency;
  IF @Run IS NULL BEGIN COMMIT TRANSACTION; RETURN; END;

  -- Warehouse keys are not enforced: reject join fan-out or lost reference data before serving totals.
  IF EXISTS (SELECT customer_key FROM gold.dim_customer GROUP BY customer_key HAVING COUNT_BIG(*)>1)
    OR EXISTS (SELECT content_key FROM gold.dim_content GROUP BY content_key HAVING COUNT_BIG(*)>1)
    OR EXISTS (SELECT campaign_key FROM gold.dim_campaign GROUP BY campaign_key HAVING COUNT_BIG(*)>1)
    OR EXISTS (SELECT distributor_key FROM gold.dim_distributor GROUP BY distributor_key HAVING COUNT_BIG(*)>1)
    OR EXISTS (SELECT currency FROM gold.currency GROUP BY currency HAVING COUNT_BIG(*)>1)
    OR EXISTS (SELECT order_id,line_number FROM gold.fact_order_line GROUP BY order_id,line_number HAVING COUNT_BIG(*)>1)
    OR EXISTS (SELECT order_id FROM gold.fact_order_line GROUP BY order_id HAVING COUNT(DISTINCT customer_key)>1 OR COUNT(DISTINCT currency)>1)
    OR EXISTS (SELECT touch_key FROM gold.fact_campaign_touch GROUP BY touch_key HAVING COUNT_BIG(*)>1)
    OR EXISTS (SELECT session_id FROM gold.fact_playback_session GROUP BY session_id HAVING COUNT_BIG(*)>1)
    OR EXISTS (SELECT 1 FROM gold.currency WHERE minor_exponent NOT BETWEEN 0 AND 4 OR minor_exponent IS NULL)
    OR EXISTS (SELECT 1 FROM gold.fact_order_line f
      LEFT JOIN gold.dim_customer u ON u.customer_key=f.customer_key
      LEFT JOIN gold.dim_content c ON c.content_key=f.content_key
      LEFT JOIN gold.currency fx ON fx.currency=f.currency
      WHERE u.customer_key IS NULL OR c.content_key IS NULL OR fx.currency IS NULL OR f.amount_minor<0)
    OR EXISTS (SELECT 1 FROM gold.fact_campaign_touch t
      LEFT JOIN gold.dim_customer u ON u.customer_key=t.customer_key
      LEFT JOIN gold.dim_campaign c ON c.campaign_key=t.campaign_key
      WHERE u.customer_key IS NULL OR c.campaign_key IS NULL)
    OR EXISTS (SELECT 1 FROM gold.fact_order_line f WHERE NULLIF(f.campaign_key,'') IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM gold.dim_campaign c WHERE c.campaign_key=f.campaign_key))
    OR EXISTS (SELECT 1 FROM gold.fact_campaign_conversion c
      WHERE NOT EXISTS (SELECT 1 FROM gold.fact_order_line f WHERE f.order_id=c.order_id AND f.customer_key=c.customer_key)
        OR NOT EXISTS (SELECT 1 FROM gold.dim_campaign d WHERE d.campaign_key=c.campaign_key))
    OR EXISTS (SELECT 1 FROM gold.fact_playback_session p WHERE p.position_seconds<0
      OR NOT EXISTS (SELECT 1 FROM gold.fact_order_line f WHERE f.order_id=p.order_id AND f.customer_key=p.customer_key AND f.content_key=p.content_key))
    THROW 51021, 'Campaign Gold integrity check failed', 1;
  IF NOT EXISTS (SELECT 1 FROM gold.currency WHERE currency=@SelectedCurrency)
    AND EXISTS (SELECT 1 FROM gold.currency) THROW 51022, 'Select a published currency', 1;

  SELECT TOP (33) currency,minor_exponent FROM gold.currency ORDER BY currency;
  SELECT DISTINCT TOP (65) COALESCE(NULLIF(territory,''),'Unknown') AS territory FROM gold.dim_customer ORDER BY territory;
  SELECT TOP (201) campaign_key,COALESCE(NULLIF(name,''),campaign_key) AS name FROM gold.dim_campaign ORDER BY name,campaign_key;
  ${COHORT} SELECT ${METRICS} FROM cohort;
  ${COHORT} SELECT TOP (201) c.campaign_key,COALESCE(NULLIF(d.name,''),c.campaign_key) AS name, ${METRICS}
    FROM cohort c JOIN gold.dim_campaign d ON d.campaign_key=c.campaign_key
    GROUP BY c.campaign_key,d.name
    ORDER BY SUM(CASE WHEN engaged=1 THEN CAST(amount_minor AS decimal(38,0)) ELSE 0 END) DESC,c.campaign_key;
  ${COHORT} SELECT CONVERT(varchar(10),cohort_date,23) AS date, ${METRICS}
    FROM cohort GROUP BY cohort_date ORDER BY cohort_date;
  ${COHORT} SELECT TOP (12) content_key,title,genre,distributor,
    COUNT_BIG(DISTINCT order_id) AS orders,
    COUNT_BIG(DISTINCT CASE WHEN engaged=1 THEN order_id END) AS engaged_orders,
    CONVERT(varchar(40),SUM(CAST(amount_minor AS decimal(38,0)))) AS booked_minor,
    CONVERT(varchar(40),SUM(CASE WHEN engaged=1 THEN CAST(amount_minor AS decimal(38,0)) ELSE 0 END)) AS engaged_minor
    FROM cohort WHERE record_kind='order' GROUP BY content_key,title,genre,distributor
    ORDER BY SUM(CASE WHEN engaged=1 THEN CAST(amount_minor AS decimal(38,0)) ELSE 0 END) DESC,
      SUM(CAST(amount_minor AS decimal(38,0))) DESC,content_key;
  SELECT COUNT_BIG(DISTINCT CASE WHEN attribution_status='unattributed' THEN order_id END) AS unattributed_orders,
    COUNT_BIG(DISTINCT CASE WHEN attribution_status='without_contact' THEN order_id END) AS linked_without_touch_orders,
    COUNT_BIG(DISTINCT CASE WHEN attribution_status='ambiguous' THEN order_id END) AS ambiguous_orders,
    CONVERT(varchar(40),COALESCE(SUM(CAST(amount_minor AS decimal(38,0))),0)) AS excluded_minor
    FROM gold.campaign_engaged_revenue
    WHERE record_kind='order' AND attribution_status<>'recorded'
      AND created_date BETWEEN @StartDate AND @EndDate AND currency=@SelectedCurrency
      AND (@territory='' OR territory=@territory) AND (@campaign_key='' OR campaign_key=@campaign_key)
    OPTION (LABEL = 'MSFlix_CampaignImpact');
  COMMIT TRANSACTION;
END TRY
BEGIN CATCH
  IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
  THROW;
END CATCH;`;

type Row = Record<string, unknown>;
type Source = Pick<AnalyticsBinding, 'name' | 'workspace_id' | 'item_id'>;
function invalid(): never { throw new Error(INVALID); }
function text(value: unknown, max: number): string {
  if (typeof value !== 'string' || !value.length || value.length > max) invalid();
  return value;
}
function integer(value: unknown): string {
  if (typeof value === 'number' && (!Number.isSafeInteger(value) || value < 0)) invalid();
  if ((typeof value !== 'string' && typeof value !== 'number') || !/^(0|[1-9]\d{0,37})$/.test(String(value))) invalid();
  return String(value);
}
function count(value: unknown): number {
  const result = Number(integer(value));
  if (!Number.isSafeInteger(result)) invalid();
  return result;
}
function money(value: unknown): string {
  if (typeof value !== 'string') invalid();
  return integer(value);
}
function timestamp(value: unknown): string {
  if (!(value instanceof Date) && typeof value !== 'string') invalid();
  const result = new Date(value);
  if (!Number.isFinite(result.getTime())) invalid();
  return result.toISOString();
}
function unique(values: string[]): void { if (new Set(values).size !== values.length) invalid(); }
function zeroMetrics(): CampaignImpactMetrics {
  return { contacted_customers: 0, touches: 0, buyers: 0, orders: 0, played_orders: 0, engaged_orders: 0,
    unknown_duration_orders: 0, booked_minor: '0', engaged_minor: '0', not_started_minor: '0', engaged_per_100_minor: null };
}
function metrics(row: Row): CampaignImpactMetrics {
  const result: CampaignImpactMetrics = {
    contacted_customers: count(row.contacted_customers), touches: count(row.touches), buyers: count(row.buyers),
    orders: count(row.orders), played_orders: count(row.played_orders), engaged_orders: count(row.engaged_orders),
    unknown_duration_orders: count(row.unknown_duration_orders), booked_minor: money(row.booked_minor),
    engaged_minor: money(row.engaged_minor), not_started_minor: money(row.not_started_minor), engaged_per_100_minor: null,
  };
  const r = result;
  if (r.buyers > r.contacted_customers || r.buyers > r.orders || r.contacted_customers > r.touches
    || r.played_orders > r.orders || r.engaged_orders > r.played_orders || r.unknown_duration_orders > r.orders
    || BigInt(r.engaged_minor) + BigInt(r.not_started_minor) > BigInt(r.booked_minor)
    || (!r.orders && (r.booked_minor !== '0' || r.buyers !== 0)) || (r.orders > 0 && !r.buyers)) invalid();
  if (r.contacted_customers) {
    const denominator = BigInt(r.contacted_customers);
    r.engaged_per_100_minor = ((BigInt(r.engaged_minor) * 100n + denominator / 2n) / denominator).toString();
  }
  return r;
}

export function campaignFromRecordsets(source: Source, filters: CampaignImpactFilters, sets: unknown): CampaignImpact {
  if (!Array.isArray(sets)) invalid();
  const rows = (index: number, limit: number): Row[] => {
    const value: unknown = sets[index];
    if (!Array.isArray(value) || value.length > limit || value.some(r => !r || typeof r !== 'object' || Array.isArray(r))) invalid();
    return value as Row[];
  };
  const one = (index: number): Row => { const r = rows(index, 1); if (r.length !== 1) invalid(); return r[0]; };
  const meta = one(0), from = date(meta.date_from), to = date(meta.date_to);
  dateRange(from, to);
  if (typeof meta.currency !== 'string' || (meta.currency !== '' && !/^[A-Z]{3}$/.test(meta.currency))) invalid();
  const currency = meta.currency;
  if ((filters.currency && filters.currency !== currency) || (filters.from && filters.from !== from) || (filters.to && filters.to !== to)) invalid();
  const published = meta.run_id !== null;
  const result: CampaignImpact = {
    source: { name: source.name, workspace_id: source.workspace_id, item_id: source.item_id,
      view: 'gold.campaign_engaged_revenue' }, state: 'unpublished',
    freshness: { queried_at: timestamp(meta.queried_at), published_at: published ? timestamp(meta.completed_at) : null,
      publication_run_id: published ? text(meta.run_id, 128) : null },
    filters: { ...filters, from, to, currency }, options: { currencies: [], territories: [], campaigns: [] },
    summary: zeroMetrics(), campaigns: [], trend: [], titles: [],
    coverage: { unattributed_orders: 0, linked_without_touch_orders: 0, ambiguous_orders: 0, excluded_minor: '0' },
    methodology: { attribution: 'recorded_only', cohort: 'first_campaign_contact', contact_window_days: null,
      engagement_percent: 80, coverage_dates: 'order_created' },
  };
  if (!published) return result;
  if (sets.length !== 9) invalid();
  result.options.currencies = rows(1, CAMPAIGN_LIMITS.currencies).map(r => {
    const code = text(r.currency, 3), exponent = count(r.minor_exponent);
    if (!/^[A-Z]{3}$/.test(code) || exponent > 4) invalid();
    return { currency: code, minor_exponent: exponent };
  });
  result.options.territories = rows(2, CAMPAIGN_LIMITS.territories).map(r => text(r.territory, 64));
  result.options.campaigns = rows(3, CAMPAIGN_LIMITS.campaigns).map(r => ({ campaign_key: text(r.campaign_key, 128), name: text(r.name, 300) }));
  unique(result.options.currencies.map(r => r.currency)); unique(result.options.territories); unique(result.options.campaigns.map(r => r.campaign_key));
  if (currency && !result.options.currencies.some(r => r.currency === currency)) invalid();
  result.summary = metrics(one(4));
  result.state = result.summary.contacted_customers || result.summary.orders ? 'ready' : 'empty';
  result.campaigns = rows(5, CAMPAIGN_LIMITS.campaigns).map(r => ({ ...metrics(r), campaign_key: text(r.campaign_key, 128), name: text(r.name, 300) }));
  unique(result.campaigns.map(r => r.campaign_key));
  if (result.campaigns.some(r => !result.options.campaigns.some(c => c.campaign_key === r.campaign_key))) invalid();
  const trend = rows(6, CAMPAIGN_LIMITS.days).map(r => ({ ...metrics(r), date: date(r.date) }));
  unique(trend.map(r => r.date));
  if (trend.some(r => r.date < from || r.date > to)) invalid();
  const byDate = new Map(trend.map(r => [r.date, r]));
  for (let day = Date.parse(from); day <= Date.parse(to); day += DAY_MS) {
    const key = new Date(day).toISOString().slice(0, 10);
    result.trend.push(byDate.get(key) ?? { date: key, ...zeroMetrics() });
  }
  result.titles = rows(7, CAMPAIGN_LIMITS.titles).map(r => {
    const item = { content_key: text(r.content_key, 128), title: text(r.title, 500), genre: text(r.genre, 128), distributor: text(r.distributor, 300),
      orders: count(r.orders), engaged_orders: count(r.engaged_orders), booked_minor: money(r.booked_minor), engaged_minor: money(r.engaged_minor) };
    if (item.engaged_orders > item.orders || BigInt(item.engaged_minor) > BigInt(item.booked_minor)) invalid();
    return item;
  });
  unique(result.titles.map(r => r.content_key));
  for (const list of [result.campaigns, result.trend]) {
    for (const key of ['booked_minor', 'engaged_minor', 'not_started_minor'] as const)
      if (list.reduce((sum, row) => sum + BigInt(row[key]), 0n) !== BigInt(result.summary[key])) invalid();
    for (const key of ['orders', 'played_orders', 'engaged_orders', 'unknown_duration_orders', 'touches'] as const)
      if (list.reduce((sum, row) => sum + BigInt(row[key]), 0n) !== BigInt(result.summary[key])) invalid();
  }
  for (const key of ['booked_minor', 'engaged_minor'] as const)
    if (result.titles.reduce((sum, row) => sum + BigInt(row[key]), 0n) > BigInt(result.summary[key])) invalid();
  const c = one(8);
  result.coverage = { unattributed_orders: count(c.unattributed_orders), linked_without_touch_orders: count(c.linked_without_touch_orders),
    ambiguous_orders: count(c.ambiguous_orders), excluded_minor: money(c.excluded_minor) };
  return result;
}

export async function readCampaignImpact(binding: AnalyticsBinding, token: string, json: string): Promise<CampaignImpact> {
  const filters = parseCampaignFilters(json);
  const pool = goldPool(binding, token);
  try {
    await connectGoldPool(pool);
    const result = await pool.request()
      .input('from_date', sql.Date, filters.from ? new Date(`${filters.from}T00:00:00.000Z`) : null)
      .input('to_date', sql.Date, filters.to ? new Date(`${filters.to}T00:00:00.000Z`) : null)
      .input('territory', sql.VarChar(64), filters.territory)
      .input('campaign_key', sql.VarChar(128), filters.campaignKey)
      .input('currency', sql.VarChar(3), filters.currency)
      .input('query_time', sql.DateTime2(6), new Date())
      .query(GOLD_CAMPAIGN_QUERY);
    return campaignFromRecordsets(binding, filters, result.recordsets);
  } catch { throw new Error(UNAVAILABLE); }
  finally { try { await pool.close(); } catch { throw new Error(UNAVAILABLE); } }
}
