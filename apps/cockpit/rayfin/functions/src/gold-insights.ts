import sql from 'mssql';
import type { AnalyticsBinding } from '../../data/schema.js';
import { connectGoldPool, goldPool } from './gold-dashboard.js';
import type { GoldInsights, GoldInsightsFilters } from './gold-insights-contract.js';

export type { GoldInsights, GoldInsightsFilters } from './gold-insights-contract.js';

export const INSIGHTS_LIMITS = { days: 366, territories: 50, genres: 128, currencies: 32, titles: 12, heatmapGenres: 12 } as const;
const DAY_MS = 86_400_000;
const UNAVAILABLE = 'MSFlixGold insights unavailable. Verify the published Gold contract and app-identity SELECT access. No operational fallback.';
const INVALID_DATA = 'Published Gold insights failed an integrity or result-boundary check. No partial totals are presented.';

function dateValue(value: unknown): string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)
    || value < '1000-01-01' || value > '9998-12-31') throw new Error('Use ISO dates in YYYY-MM-DD form.');
  const parsed = new Date(`${value}T00:00:00.000Z`);
  if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value)
    throw new Error('Use a real calendar date in YYYY-MM-DD form.');
  return value;
}
function dateRange(from: string, to: string): void {
  const days = (Date.parse(to) - Date.parse(from)) / DAY_MS + 1;
  if (days < 1 || days > INSIGHTS_LIMITS.days) throw new Error('Select an ordered, inclusive date range of at most 366 days.');
}

/** Validate before opening SQL; quotation marks remain ordinary parameter values. */
export function parseInsightsFilters(filtersJson: string): GoldInsightsFilters {
  if (typeof filtersJson !== 'string' || filtersJson.length > 2048) throw new Error('Insights filters must be a small JSON object.');
  let value: unknown;
  try { value = JSON.parse(filtersJson); } catch { throw new Error('Insights filters must be valid JSON.'); }
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Insights filters must be a JSON object.');
  const input = value as Record<string, unknown>;
  const permitted = ['from', 'to', 'territory', 'genre', 'transactionType', 'currency'];
  if (Object.keys(input).some(key => !permitted.includes(key))) throw new Error('Unsupported Insights filter.');
  const text = (key: string, max: number): string => {
    const field = input[key] === undefined ? '' : input[key];
    if (typeof field !== 'string' || field.length > max || /[\u0000-\u001f\u007f]/.test(field))
      throw new Error('Insights filter value has an invalid type or length.');
    return field;
  };
  const from = text('from', 10), to = text('to', 10);
  if (from) dateValue(from);
  if (to) dateValue(to);
  if (from && to) dateRange(from, to);
  const transactionType = text('transactionType', 4);
  if (transactionType !== '' && transactionType !== 'TVOD' && transactionType !== 'EST')
    throw new Error('Select TVOD, EST, or all transaction types.');
  const currency = text('currency', 3);
  if (currency && currency !== '*' && !/^[A-Z]{3}$/.test(currency)) throw new Error('Select ALL or an uppercase three-letter currency.');
  return { from, to, territory: text('territory', 64), genre: text('genre', 128), transactionType, currency };
}

/* Repeated CTEs are server-side full-cohort aggregates, not a recent-activity export.
   Playback keys deliberately exclude money and line_number: one session must not
   multiply order lines, including multiple lines for the same title. */
const COHORT = `WITH cohort AS (
  SELECT f.order_id, f.line_number, f.customer_key, f.content_key,
    COALESCE(NULLIF(f.territory,''),'Unknown') AS territory,
    COALESCE(NULLIF(c.genre,''),'Unknown') AS genre,
    COALESCE(NULLIF(c.title,''),f.content_key) AS title, c.duration_seconds,
    CAST(f.created_at AS date) AS order_date,
    CASE WHEN @SelectedCurrency='*' THEN CAST(f.amount_minor AS decimal(38,0)) *
      CASE fx.minor_exponent WHEN 0 THEN 10000 WHEN 1 THEN 1000 WHEN 2 THEN 100 WHEN 3 THEN 10 ELSE 1 END
      ELSE CAST(f.amount_minor AS decimal(38,0)) END AS amount_minor,
    f.first_play_at
  FROM gold.fact_order_line f
  JOIN gold.dim_content c ON c.content_key=f.content_key
  JOIN gold.dim_customer u ON u.customer_key=f.customer_key
  JOIN gold.dim_offer o ON o.offer_key=f.offer_key AND o.content_key=f.content_key
    AND o.currency=f.currency AND o.transaction_type=f.transaction_type
  JOIN gold.currency fx ON fx.currency=f.currency
  WHERE f.created_at>=@StartDate AND f.created_at<DATEADD(day,1,@EndDate)
    AND (@SelectedCurrency='*' OR f.currency=@SelectedCurrency)
    AND (@territory='' OR COALESCE(NULLIF(f.territory,''),'Unknown')=@territory)
    AND (@genre='' OR COALESCE(NULLIF(c.genre,''),'Unknown')=@genre)
    AND (@transaction_type='' OR f.transaction_type=@transaction_type)
), playback_keys AS (
  SELECT DISTINCT order_id, customer_key, content_key, order_date, territory, genre, duration_seconds FROM cohort
), cohort_sessions AS (
  SELECT p.session_id, p.order_id, p.customer_key, p.content_key, k.order_date, k.territory,
    CAST(CASE WHEN UPPER(p.status)='COMPLETED' THEN 1 ELSE 0 END AS bigint) AS completed,
    CASE WHEN k.duration_seconds>0 THEN
      CASE WHEN p.position_seconds<=0 THEN 0.0 WHEN p.position_seconds>=k.duration_seconds THEN 100.0
        ELSE 100.0*CAST(p.position_seconds AS float)/k.duration_seconds END
      ELSE NULL END AS progress
  FROM gold.fact_playback_session p
  JOIN playback_keys k ON k.order_id=p.order_id AND k.customer_key=p.customer_key AND k.content_key=p.content_key
)`;

/** One request, ten bounded result sets, and one snapshot transaction; only SELECT reads persistent data. */
export const GOLD_INSIGHTS_QUERY = `SET NOCOUNT ON;
SET TRANSACTION ISOLATION LEVEL SNAPSHOT;
BEGIN TRY
  BEGIN TRANSACTION;
  DECLARE @PublicationRun varchar(128), @PublishedAt datetime2(6), @MinimumDate date, @MaximumDate date;
  DECLARE @StartDate date=@from_date, @EndDate date=@to_date, @SelectedCurrency varchar(3)=NULLIF(@currency,'');
  IF OBJECT_ID('gold.publication','U') IS NOT NULL
    SELECT TOP (1) @PublicationRun=run_id, @PublishedAt=completed_at
    FROM gold.publication ORDER BY completed_at DESC,run_id;

  IF @PublicationRun IS NOT NULL
  BEGIN
    SELECT @MinimumDate=CAST(MIN(created_at) AS date), @MaximumDate=CAST(MAX(created_at) AS date) FROM gold.fact_order_line;
    IF @SelectedCurrency IS NULL
      SELECT TOP (1) @SelectedCurrency=currency FROM gold.fact_order_line GROUP BY currency ORDER BY COUNT_BIG(*) DESC,currency;
    IF @SelectedCurrency IS NULL
      SELECT TOP (1) @SelectedCurrency=currency FROM gold.currency ORDER BY currency;
  END;
  IF @StartDate IS NOT NULL AND @EndDate IS NULL
    SET @EndDate=CASE WHEN @MaximumDate BETWEEN @StartDate AND DATEADD(day,29,@StartDate)
      THEN @MaximumDate ELSE DATEADD(day,29,@StartDate) END;
  IF @EndDate IS NULL SET @EndDate=COALESCE(@MaximumDate,CAST(@query_time AS date));
  IF @StartDate IS NULL
    SET @StartDate=CASE WHEN @MinimumDate BETWEEN DATEADD(day,-29,@EndDate) AND @EndDate
      THEN @MinimumDate ELSE DATEADD(day,-29,@EndDate) END;
  IF @StartDate>@EndDate OR DATEDIFF(day,@StartDate,@EndDate)>=366
    THROW 51010, 'Invalid Insights date range', 1;

  SELECT @PublicationRun AS run_id, @PublishedAt AS completed_at, @query_time AS queried_at,
    CONVERT(varchar(10),@StartDate,23) AS date_from, CONVERT(varchar(10),@EndDate,23) AS date_to,
    CONVERT(varchar(10),@MinimumDate,23) AS extent_from, CONVERT(varchar(10),@MaximumDate,23) AS extent_to,
    COALESCE(@SelectedCurrency,'') AS currency;
  IF @PublicationRun IS NULL
  BEGIN
    COMMIT TRANSACTION;
    RETURN;
  END;

  -- Warehouse constraints are not enforced. Reject ambiguous joins instead of inflating or dropping money.
  IF EXISTS (SELECT content_key FROM gold.dim_content GROUP BY content_key HAVING COUNT_BIG(*)>1)
    OR EXISTS (SELECT customer_key FROM gold.dim_customer GROUP BY customer_key HAVING COUNT_BIG(*)>1)
    OR EXISTS (SELECT offer_key FROM gold.dim_offer GROUP BY offer_key HAVING COUNT_BIG(*)>1)
    OR EXISTS (SELECT campaign_key FROM gold.dim_campaign GROUP BY campaign_key HAVING COUNT_BIG(*)>1)
    OR EXISTS (SELECT currency FROM gold.currency GROUP BY currency HAVING COUNT_BIG(*)>1)
    OR EXISTS (SELECT order_id,line_number FROM gold.fact_order_line GROUP BY order_id,line_number HAVING COUNT_BIG(*)>1)
    OR EXISTS (SELECT session_id FROM gold.fact_playback_session GROUP BY session_id HAVING COUNT_BIG(*)>1)
    OR EXISTS (SELECT consent_key FROM gold.fact_customer_consent GROUP BY consent_key HAVING COUNT_BIG(*)>1)
    OR EXISTS (SELECT touch_key FROM gold.fact_campaign_touch GROUP BY touch_key HAVING COUNT_BIG(*)>1)
    OR EXISTS (SELECT conversion_key FROM gold.fact_campaign_conversion GROUP BY conversion_key HAVING COUNT_BIG(*)>1)
    THROW 51011, 'Nonunique Gold business key', 1;
  IF EXISTS (
    SELECT 1 FROM gold.fact_order_line f
    LEFT JOIN gold.dim_content c ON c.content_key=f.content_key
    LEFT JOIN gold.dim_customer u ON u.customer_key=f.customer_key
    LEFT JOIN gold.dim_offer o ON o.offer_key=f.offer_key AND o.content_key=f.content_key
      AND o.currency=f.currency AND o.transaction_type=f.transaction_type
    LEFT JOIN gold.currency fx ON fx.currency=f.currency
    WHERE c.content_key IS NULL OR u.customer_key IS NULL OR o.offer_key IS NULL OR fx.currency IS NULL OR f.amount_minor<0
  ) OR EXISTS (SELECT 1 FROM gold.currency WHERE minor_exponent IS NULL OR minor_exponent NOT BETWEEN 0 AND 4)
    THROW 51012, 'Unresolved Gold commercial contract', 1;
  IF EXISTS (
    SELECT order_id,customer_key,content_key FROM gold.fact_order_line GROUP BY order_id,customer_key,content_key
    HAVING MIN(CAST(created_at AS date))<>MAX(CAST(created_at AS date)) OR MIN(currency)<>MAX(currency)
      OR MIN(transaction_type)<>MAX(transaction_type)
      OR MIN(COALESCE(NULLIF(territory,''),'Unknown'))<>MAX(COALESCE(NULLIF(territory,''),'Unknown'))
  ) THROW 51013, 'Ambiguous playback to order-line cohort', 1;

  SELECT TOP (33) currency,minor_exponent FROM gold.currency ORDER BY currency;
  WITH territories AS (
    SELECT COALESCE(NULLIF(territory,''),'Unknown') AS territory FROM gold.dim_territory
    UNION SELECT COALESCE(NULLIF(territory,''),'Unknown') FROM gold.fact_order_line
  ) SELECT TOP (51) territory FROM territories ORDER BY territory;
  SELECT DISTINCT TOP (129) COALESCE(NULLIF(genre,''),'Unknown') AS genre FROM gold.dim_content ORDER BY genre;

  ${COHORT}
  SELECT CONVERT(varchar(40),COUNT_BIG(DISTINCT order_id)) AS orders,
    CONVERT(varchar(40),COUNT_BIG(*)) AS order_lines,
    CONVERT(varchar(40),COUNT_BIG(DISTINCT customer_key)) AS customers,
    CONVERT(varchar(40),COUNT_BIG(DISTINCT content_key)) AS titles,
    CONVERT(varchar(40),COALESCE(SUM(CAST(amount_minor AS decimal(38,0))),0)) AS booked_minor,
    CONVERT(varchar(40),(SELECT COUNT_BIG(*) FROM cohort_sessions)) AS sessions,
    CONVERT(varchar(40),(SELECT COUNT_BIG(*) FROM (
      SELECT order_id FROM cohort WHERE first_play_at IS NOT NULL
      UNION SELECT order_id FROM cohort_sessions
    ) played)) AS played_orders,
    CONVERT(varchar(40),(SELECT COALESCE(SUM(completed),0) FROM cohort_sessions)) AS completed_sessions
  FROM cohort;

  ${COHORT}, daily_sessions AS (
    SELECT order_date,COUNT_BIG(*) AS sessions FROM cohort_sessions GROUP BY order_date
  )
  SELECT CONVERT(varchar(10),c.order_date,23) AS date,
    CONVERT(varchar(40),COUNT_BIG(DISTINCT c.order_id)) AS orders,
    CONVERT(varchar(40),SUM(CAST(c.amount_minor AS decimal(38,0)))) AS booked_minor,
    CONVERT(varchar(40),COALESCE(MAX(s.sessions),0)) AS sessions
  FROM cohort c LEFT JOIN daily_sessions s ON s.order_date=c.order_date
  GROUP BY c.order_date ORDER BY c.order_date;

  ${COHORT}, ranked_genres AS (
    SELECT TOP (12) genre FROM cohort GROUP BY genre ORDER BY SUM(CAST(amount_minor AS decimal(38,0))) DESC,genre
  )
  SELECT TOP (601) c.territory,c.genre,CONVERT(varchar(40),COUNT_BIG(DISTINCT c.order_id)) AS orders,
    CONVERT(varchar(40),SUM(CAST(c.amount_minor AS decimal(38,0)))) AS booked_minor
  FROM cohort c JOIN ranked_genres g ON g.genre=c.genre GROUP BY c.territory,c.genre ORDER BY c.territory,c.genre;

  ${COHORT}, title_orders AS (
    SELECT content_key,title,genre,COUNT_BIG(DISTINCT order_id) AS orders,
      SUM(CAST(amount_minor AS decimal(38,0))) AS booked_minor
    FROM cohort GROUP BY content_key,title,genre
  ), title_sessions AS (
    SELECT content_key,COUNT_BIG(*) AS sessions,SUM(completed) AS completed_sessions,AVG(progress) AS average_progress
    FROM cohort_sessions GROUP BY content_key
  )
  SELECT TOP (12) c.content_key,c.title,c.genre,CONVERT(varchar(40),c.orders) AS orders,
    CONVERT(varchar(40),c.booked_minor) AS booked_minor,
    CONVERT(varchar(40),COALESCE(s.sessions,0)) AS sessions,
    CONVERT(varchar(40),COALESCE(s.completed_sessions,0)) AS completed_sessions,s.average_progress
  FROM title_orders c LEFT JOIN title_sessions s ON s.content_key=c.content_key ORDER BY c.booked_minor DESC,c.content_key;

  ${COHORT}, territory_sessions AS (
    SELECT territory,COUNT_BIG(*) AS sessions FROM cohort_sessions GROUP BY territory
  )
  SELECT TOP (51) c.territory,CONVERT(varchar(40),COUNT_BIG(DISTINCT c.order_id)) AS orders,
    CONVERT(varchar(40),COUNT_BIG(DISTINCT c.customer_key)) AS customers,
    CONVERT(varchar(40),SUM(CAST(c.amount_minor AS decimal(38,0)))) AS booked_minor,
    CONVERT(varchar(40),COALESCE(MAX(s.sessions),0)) AS sessions
  FROM cohort c LEFT JOIN territory_sessions s ON s.territory=c.territory GROUP BY c.territory ORDER BY c.territory;

  ${COHORT}, cohort_customers AS (SELECT DISTINCT customer_key FROM cohort), latest_consent AS (
    SELECT customer_key,granted,ROW_NUMBER() OVER (
      PARTITION BY customer_key,LOWER(purpose),channel ORDER BY effective_at DESC,source_sequence DESC,event_id DESC,consent_key DESC
    ) AS current_rank
    FROM gold.fact_customer_consent WHERE LOWER(purpose)='marketing' AND effective_at<=@PublishedAt
  )
  SELECT CONVERT(varchar(40),(SELECT COUNT_BIG(*) FROM cohort_customers)) AS customer_count,
    CONVERT(varchar(40),(SELECT COUNT_BIG(*) FROM cohort_customers u WHERE EXISTS (
      SELECT 1 FROM latest_consent s WHERE s.customer_key=u.customer_key AND s.current_rank=1 AND s.granted=1
    ))) AS contactable_customers,
    CONVERT(varchar(40),(SELECT COUNT_BIG(*) FROM gold.dim_campaign WHERE @territory='' OR territory=@territory)) AS campaigns,
    CONVERT(varchar(40),(SELECT COUNT_BIG(*) FROM gold.fact_campaign_touch t
      WHERE t.occurred_at>=@StartDate AND t.occurred_at<DATEADD(day,1,@EndDate)
        AND EXISTS (SELECT 1 FROM cohort_customers u WHERE u.customer_key=t.customer_key))) AS touches,
    CONVERT(varchar(40),(SELECT COUNT_BIG(*) FROM gold.fact_campaign_conversion v
      WHERE EXISTS (SELECT 1 FROM cohort c WHERE c.order_id=v.order_id AND c.customer_key=v.customer_key))) AS conversions;
  COMMIT TRANSACTION;
END TRY
BEGIN CATCH
  IF @@TRANCOUNT>0 ROLLBACK TRANSACTION;
  THROW;
END CATCH;`;

type Row = Record<string, unknown>;
type Source = Pick<AnalyticsBinding, 'name' | 'workspace_id' | 'item_id'>;
function invalid(): never { throw new Error(INVALID_DATA); }
function text(value: unknown, max: number): string {
  if (typeof value !== 'string' || !value.length || value.length > max) invalid();
  return value;
}
function integer(value: unknown): string {
  if (typeof value === 'number' && (!Number.isSafeInteger(value) || value < 0)) invalid();
  if (typeof value !== 'string' && typeof value !== 'number') invalid();
  const result = String(value);
  if (!/^(0|[1-9]\d{0,37})$/.test(result)) invalid();
  return result;
}
function count(value: unknown): number {
  const result = Number(integer(value));
  if (!Number.isSafeInteger(result)) invalid();
  return result;
}
function money(value: unknown): string {
  // SQL returns decimal(38,0) as varchar; accepting a JS float here could already have lost cents.
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

const scope: GoldInsights['scope'] = {
  orders: 'created-at-cohort', sessions: 'latest-recorded-state-for-cohort-orders',
  money: 'booked-order-value-not-recognized-revenue',
  contactableCustomers: 'cohort-customers-current-marketing-consent-any-channel',
  campaigns: 'selected-territory-all-dates', touches: 'cohort-customer-touches-in-date-range',
  conversions: 'explicit-conversions-for-cohort-orders',
};
function sources(published: boolean): GoldInsights['sources'] {
  const state = published ? 'published' : 'not-published';
  const prefix = published ? 'Published Gold projection, not a direct source connectivity check. ' : 'No completed Gold publication. ';
  return [
    { name: 'Oracle', state, detail: `${prefix}Catalogue, offers and territories.`,
      tables: ['gold.dim_content', 'gold.dim_offer', 'gold.dim_territory'] },
    { name: 'Salesforce', state, detail: `${prefix}Customers, campaigns, marketing consents and touches; touches do not attribute booked value.`,
      tables: ['gold.dim_customer', 'gold.dim_campaign', 'gold.fact_customer_consent', 'gold.fact_campaign_touch'] },
    { name: 'RTI', state, detail: `${prefix}Current order lines, playback session state and explicit campaign conversions. Position is not watch duration.`,
      tables: ['gold.fact_order_line', 'gold.fact_playback_session', 'gold.fact_campaign_conversion'] },
    { name: 'SAP', state: 'not-published', detail: 'Local prospective contract only; no published SAP tables, invoices, revenue or margin are included.', tables: [] },
  ];
}

/** Strict boundary between driver rows and the browser's PII-free DTO. */
export function insightsFromRecordsets(source: Source, filters: GoldInsightsFilters, recordsets: unknown): GoldInsights {
  if (!Array.isArray(recordsets)) invalid();
  const rows = (index: number, limit: number): Row[] => {
    const set: unknown = recordsets[index];
    if (!Array.isArray(set) || set.length > limit || set.some(row => !row || typeof row !== 'object' || Array.isArray(row))) invalid();
    return set as Row[];
  };
  const one = (index: number): Row => { const set = rows(index, 1); if (set.length !== 1) invalid(); return set[0]; };
  const meta = one(0);
  let from: string, to: string;
  try { from = dateValue(meta.date_from); to = dateValue(meta.date_to); dateRange(from, to); } catch { invalid(); }
  const currency = meta.currency;
  if (typeof currency !== 'string' || (currency !== '' && currency !== '*' && !/^[A-Z]{3}$/.test(currency))) invalid();
  if ((filters.currency && filters.currency !== currency) || (filters.from && filters.from !== from)
    || (filters.to && filters.to !== to)) invalid();
  const published = meta.run_id !== null;
  const base: GoldInsights = {
    source: { name: source.name, workspace_id: source.workspace_id, item_id: source.item_id },
    state: 'unpublished',
    freshness: { queried_at: timestamp(meta.queried_at), published_at: published ? timestamp(meta.completed_at) : null,
      publication_run_id: published ? text(meta.run_id, 128) : null },
    filters: { ...filters, from, to, currency },
    options: { from: null, to: null, territories: [], genres: [], currencies: [], currencyMinorExponents: [] },
    scope: { ...scope, money: currency === '*' ? 'nominal-booked-order-value-no-fx' : scope.money },
    summary: { orders: 0, orderLines: 0, customers: 0, titles: 0, bookedMinor: '0', sessions: 0, playedOrders: 0, completedSessions: 0 },
    daily: [], heatmap: [], titles: [], territories: [],
    audience: { customerCount: 0, contactableCustomers: null, campaigns: 0, touches: null, conversions: null },
    sources: sources(published),
  };
  // Do not expose even options or supplied fact rows when the serving gate is closed.
  if (!published) return base;
  if (recordsets.length !== 10) invalid();
  const currencies = rows(1, INSIGHTS_LIMITS.currencies).map(row => {
    const code = text(row.currency, 3), minorExponent = count(row.minor_exponent);
    if (!/^[A-Z]{3}$/.test(code) || minorExponent > 4) invalid();
    return { currency: code, minorExponent };
  });
  base.options.currencies = currencies.map(row => row.currency);
  base.options.currencyMinorExponents = currencies;
  base.options.territories = rows(2, INSIGHTS_LIMITS.territories).map(row => text(row.territory, 64));
  base.options.genres = rows(3, INSIGHTS_LIMITS.genres).map(row => text(row.genre, 128));
  [base.options.currencies, base.options.territories, base.options.genres].forEach(unique);
  if ((meta.extent_from === null) !== (meta.extent_to === null)) invalid();
  try {
    base.options.from = meta.extent_from === null ? null : dateValue(meta.extent_from);
    base.options.to = meta.extent_to === null ? null : dateValue(meta.extent_to);
  } catch { invalid(); }
  if (base.options.from && base.options.to && base.options.from > base.options.to) invalid();

  const s = one(4);
  base.summary = { orders: count(s.orders), orderLines: count(s.order_lines), customers: count(s.customers),
    titles: count(s.titles), bookedMinor: money(s.booked_minor), sessions: count(s.sessions),
    playedOrders: count(s.played_orders), completedSessions: count(s.completed_sessions) };
  const total = base.summary;
  if (total.orders > total.orderLines || total.customers > total.orderLines || total.titles > total.orderLines
    || total.playedOrders > total.orders || total.completedSessions > total.sessions
    || (total.orderLines > 0 && (!base.options.from || !base.options.currencies.length
      || (currency !== '*' && !base.options.currencies.includes(currency))))) invalid();
  base.state = total.orderLines ? 'ready' : 'empty';

  const daily = rows(5, INSIGHTS_LIMITS.days).map(row => {
    let date: string;
    try { date = dateValue(row.date); } catch { invalid(); }
    if (date < from || date > to) invalid();
    return { date, orders: count(row.orders), bookedMinor: money(row.booked_minor), sessions: count(row.sessions) };
  });
  unique(daily.map(row => row.date));
  const byDate = new Map(daily.map(row => [row.date, row]));
  for (let day = Date.parse(from); day <= Date.parse(to); day += DAY_MS) {
    const date = new Date(day).toISOString().slice(0, 10);
    base.daily.push(byDate.get(date) ?? { date, orders: 0, bookedMinor: '0', sessions: 0 });
  }
  base.heatmap = rows(6, INSIGHTS_LIMITS.territories * INSIGHTS_LIMITS.heatmapGenres).map(row => ({
    territory: text(row.territory, 64), genre: text(row.genre, 128), orders: count(row.orders), bookedMinor: money(row.booked_minor),
  }));
  unique(base.heatmap.map(row => JSON.stringify([row.territory, row.genre])));
  if (new Set(base.heatmap.map(row => row.genre)).size > INSIGHTS_LIMITS.heatmapGenres) invalid();
  base.titles = rows(7, INSIGHTS_LIMITS.titles).map(row => {
    const averageProgress = row.average_progress;
    if (averageProgress !== null && (typeof averageProgress !== 'number'
      || !Number.isFinite(averageProgress) || averageProgress < 0 || averageProgress > 100)) invalid();
    const sessions = count(row.sessions), completedSessions = count(row.completed_sessions);
    if (completedSessions > sessions) invalid();
    return { contentKey: text(row.content_key, 128), title: text(row.title, 500), genre: text(row.genre, 128),
      orders: count(row.orders), bookedMinor: money(row.booked_minor), sessions, completedSessions, averageProgress };
  });
  unique(base.titles.map(row => row.contentKey));
  if (base.titles.length > total.titles) invalid();
  base.territories = rows(8, INSIGHTS_LIMITS.territories).map(row => ({
    territory: text(row.territory, 64), orders: count(row.orders), customers: count(row.customers),
    bookedMinor: money(row.booked_minor), sessions: count(row.sessions),
  }));
  unique(base.territories.map(row => row.territory));
  for (const list of [base.daily, base.territories]) {
    if (list.reduce((sum, row) => sum + BigInt(row.bookedMinor), 0n) !== BigInt(total.bookedMinor)
      || list.reduce((sum, row) => sum + BigInt(row.sessions), 0n) !== BigInt(total.sessions)) invalid();
  }
  for (const list of [base.heatmap, base.titles]) {
    if (list.reduce((sum, row) => sum + BigInt(row.bookedMinor), 0n) > BigInt(total.bookedMinor)) invalid();
  }
  const a = one(9);
  base.audience = { customerCount: count(a.customer_count), contactableCustomers: a.contactable_customers === null ? null : count(a.contactable_customers),
    campaigns: count(a.campaigns), touches: a.touches === null ? null : count(a.touches),
    conversions: a.conversions === null ? null : count(a.conversions) };
  if (base.audience.customerCount !== total.customers || (base.audience.contactableCustomers ?? 0) > total.customers) invalid();
  return base;
}

export async function readGoldInsights(binding: AnalyticsBinding, token: string, filtersJson: string): Promise<GoldInsights> {
  const filters = parseInsightsFilters(filtersJson);
  const pool = goldPool(binding, token);
  try {
    await connectGoldPool(pool);
    const result = await pool.request()
      .input('from_date', sql.Date, filters.from ? new Date(`${filters.from}T00:00:00.000Z`) : null)
      .input('to_date', sql.Date, filters.to ? new Date(`${filters.to}T00:00:00.000Z`) : null)
      .input('territory', sql.VarChar(64), filters.territory)
      .input('genre', sql.VarChar(128), filters.genre)
      .input('transaction_type', sql.VarChar(4), filters.transactionType)
      .input('currency', sql.VarChar(3), filters.currency)
      .input('query_time', sql.DateTime2(6), new Date())
      .query(GOLD_INSIGHTS_QUERY);
    return insightsFromRecordsets(binding, filters, result.recordsets);
  } catch {
    throw new Error(UNAVAILABLE);
  } finally {
    try { await pool.close(); } catch { throw new Error(UNAVAILABLE); }
  }
}
