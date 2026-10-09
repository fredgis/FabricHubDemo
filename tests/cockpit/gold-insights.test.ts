// @vitest-environment node
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AnalyticsBinding } from '../../apps/cockpit/rayfin/data/schema';

const calls = vi.hoisted(() => ({
  connections: 0, closes: 0, pools: 0, queries: [] as string[], inputs: {} as Record<string, unknown>,
  sets: [] as unknown[], connectError: null as Error | null, queryError: null as Error | null, closeError: null as Error | null,
}));
vi.mock('../../apps/cockpit/rayfin/functions/node_modules/mssql', () => ({
  default: {
    Date: 'Date', DateTime2: () => 'DateTime2', VarChar: (length: number) => `VarChar(${length})`,
    ConnectionPool: class {
      constructor() { calls.pools++; }
      async connect() { calls.connections++; if (calls.connectError) throw calls.connectError; return this; }
      async close() { calls.closes++; if (calls.closeError) throw calls.closeError; }
      request() {
        const request = {
          input: (key: string, _type: unknown, value: unknown) => { calls.inputs[key] = value; return request; },
          query: async (query: string) => {
            calls.queries.push(query);
            if (calls.queryError) throw calls.queryError;
            return { recordsets: calls.sets };
          },
        };
        return request;
      }
    },
  },
}));
import { GOLD_INSIGHTS_QUERY, insightsFromRecordsets, parseInsightsFilters, readGoldInsights } from '../../apps/cockpit/rayfin/functions/src/gold-insights';

const binding: AnalyticsBinding = {
  id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', binding_key: 'business-gold', name: 'MSFlixGold',
  sql_server: 'fixture.datawarehouse.fabric.microsoft.com', sql_database: '55555555-5555-4555-8555-555555555555',
  item_id: '55555555-5555-4555-8555-555555555555', workspace_id: '33333333-3333-4333-8333-333333333333',
  capacity_id: '22222222-2222-4222-8222-222222222222', verified: true,
};
type Rows = Record<string, unknown>[][];
function fixture(booked = '9007199254740993123456789'): Rows {
  return [
    [{ run_id: 'gold-publication-not-producer-run', completed_at: new Date('2026-10-09T12:00:00Z'),
      queried_at: new Date('2026-10-09T12:30:00Z'), date_from: '2026-10-07', date_to: '2026-10-09',
      extent_from: '2025-01-01', extent_to: '2026-10-09', currency: 'EUR' }],
    [{ currency: 'EUR', minor_exponent: 2 }, { currency: 'JPY', minor_exponent: 0 }, { currency: 'USD', minor_exponent: 2 }],
    [{ territory: 'FR' }, { territory: 'US' }], [{ genre: 'Drama' }, { genre: 'Action' }],
    [{ orders: '1', order_lines: '2', customers: '1', titles: '1', booked_minor: booked,
      sessions: '2', played_orders: '1', completed_sessions: '1' }],
    [{ date: '2026-10-08', orders: '1', booked_minor: booked, sessions: '2' }],
    [{ territory: 'FR', genre: 'Drama', orders: '1', booked_minor: booked }],
    [{ content_key: 'film-1', title: 'Published film', genre: 'Drama', orders: '1', booked_minor: booked,
      sessions: '2', completed_sessions: '1', average_progress: 75 }],
    [{ territory: 'FR', orders: '1', customers: '1', booked_minor: booked, sessions: '2' }],
    [{ customer_count: '1', contactable_customers: '1', campaigns: '3', touches: '4', conversions: '1' }],
  ];
}
function empty(): Rows {
  const sets = fixture('0');
  sets[4] = [{ orders: '0', order_lines: '0', customers: '0', titles: '0', booked_minor: '0',
    sessions: '0', played_orders: '0', completed_sessions: '0' }];
  for (const index of [5, 6, 7, 8]) sets[index] = [];
  sets[9] = [{ customer_count: '0', contactable_customers: '0', campaigns: '3', touches: '0', conversions: '0' }];
  return sets;
}
const defaultFilters = () => parseInsightsFilters('{}');
beforeEach(() => {
  calls.connections = 0; calls.closes = 0; calls.pools = 0; calls.queries = []; calls.inputs = {};
  calls.sets = fixture(); calls.connectError = null; calls.queryError = null; calls.closeError = null;
});
afterEach(() => vi.useRealTimers());

describe('strict parameterized filters', () => {
  it('accepts empty JSON for SQL-resolved defaults and actual transaction codes', () => {
    expect(defaultFilters()).toEqual({ from: '', to: '', territory: '', genre: '', currency: '', transactionType: '' });
    expect(parseInsightsFilters('{"transactionType":"TVOD"}').transactionType).toBe('TVOD');
    expect(parseInsightsFilters('{"transactionType":"EST"}').transactionType).toBe('EST');
  });
  it.each(['2026-02-29', '2024-02-30', '2026-06-31', '2026-13-01', '2026-1-01', '2026-10-09T00:00:00Z', '0000-01-01'])
    ('rejects invalid or non-ISO date %s', value => expect(() => parseInsightsFilters(JSON.stringify({ from: value }))).toThrow());
  it('accepts a leap-year 366-day inclusive range, but not a 367th day or reversed range', () => {
    expect(parseInsightsFilters('{"from":"2024-01-01","to":"2024-12-31"}').from).toBe('2024-01-01');
    expect(() => parseInsightsFilters('{"from":"2024-01-01","to":"2025-01-01"}')).toThrow('366');
    expect(() => parseInsightsFilters('{"from":"2026-10-09","to":"2026-10-08"}')).toThrow('ordered');
  });
  it.each(['null', '[]', 'false', '42', 'broken', '{"territory":null}', '{"genre":7}', '{"from":true}',
    '{"extra":1}', '{"__proto__":{"currency":"USD"}}', '{"currency":"eur"}', '{"currency":"EUR,USD"}',
    '{"transactionType":"RENTAL"}', '{"transactionType":"PURCHASE"}', '{"genre":"line\\nfeed"}'])
    ('rejects malformed input %s', value => expect(() => parseInsightsFilters(value)).toThrow());
  it('rejects excessive filter input before opening SQL', async () => {
    await expect(readGoldInsights(binding, 'test-token', JSON.stringify({ genre: 'x'.repeat(2049) }))).rejects.toThrow();
    expect(calls.pools).toBe(0);
  });
  it('sends quotes and attempted SQL syntax only as typed parameters', async () => {
    const genre = "Drama'; DROP TABLE gold.fact_order_line;--";
    const territory = "FR' OR 1=1--";
    const result = await readGoldInsights(binding, 'test-token', JSON.stringify({ genre, territory, currency: 'EUR',
      transactionType: 'TVOD', from: '2026-10-07', to: '2026-10-09' }));
    expect(calls.inputs).toMatchObject({ genre, territory, currency: 'EUR', transaction_type: 'TVOD',
      from_date: new Date('2026-10-07T00:00:00Z'), to_date: new Date('2026-10-09T00:00:00Z') });
    expect(calls.queries[0]).not.toContain(genre);
    expect(calls.queries[0]).not.toContain(territory);
    expect(result.filters.genre).toBe(genre);
  });
});

describe('exact, bounded, honest browser contract', () => {
  it('preserves money beyond JS safe integers and exposes true publication metadata', () => {
    const result = insightsFromRecordsets(binding, defaultFilters(), fixture());
    expect(result.summary.bookedMinor).toBe('9007199254740993123456789');
    expect(result.titles[0].bookedMinor).toBe(result.summary.bookedMinor);
    expect(result.freshness).toEqual({ queried_at: '2026-10-09T12:30:00.000Z', published_at: '2026-10-09T12:00:00.000Z',
      publication_run_id: 'gold-publication-not-producer-run' });
    expect(result.options.currencyMinorExponents).toContainEqual({ currency: 'JPY', minorExponent: 0 });
  });
  it('returns global date/options extents, not the selected window, and zero-fills every cohort day', () => {
    const result = insightsFromRecordsets(binding, defaultFilters(), fixture());
    expect(result.options.from).toBe('2025-01-01');
    expect(result.options.territories).toEqual(['FR', 'US']);
    expect(result.daily).toEqual([
      { date: '2026-10-07', orders: 0, bookedMinor: '0', sessions: 0 },
      { date: '2026-10-08', orders: 1, bookedMinor: result.summary.bookedMinor, sessions: 2 },
      { date: '2026-10-09', orders: 0, bookedMinor: '0', sessions: 0 },
    ]);
  });
  it('hides all facts/options/CRM counts if the publication gate is closed', () => {
    const sets = fixture(); sets[0][0].run_id = null;
    sets[4][0].booked_minor = 'malformed unpublished data must not escape';
    const result = insightsFromRecordsets(binding, defaultFilters(), sets);
    expect(result.state).toBe('unpublished');
    expect(result.freshness.published_at).toBeNull();
    expect(result.freshness.publication_run_id).toBeNull();
    expect(result.options.currencies).toEqual([]);
    expect(result.daily).toEqual([]); expect(result.titles).toEqual([]);
    expect(result.audience).toEqual({ customerCount: 0, contactableCustomers: null, campaigns: 0, touches: null, conversions: null });
    expect(result.sources.every(source => source.state === 'not-published')).toBe(true);
  });
  it('distinguishes a published empty cohort from unpublished and keeps separate campaign scope', () => {
    const result = insightsFromRecordsets(binding, defaultFilters(), empty());
    expect(result.state).toBe('empty'); expect(result.summary.bookedMinor).toBe('0');
    expect(result.daily).toHaveLength(3); expect(result.audience.campaigns).toBe(3);
    expect(result.scope.campaigns).toBe('selected-territory-all-dates');
    expect(result.scope.sessions).toBe('latest-recorded-state-for-cohort-orders');
  });
  it.each([-1, '1.1', '1e20', 9007199254740992, null, '0'.repeat(50)])('rejects inexact or malformed money %s', value => {
    const sets = fixture(); sets[4][0].booked_minor = value;
    expect(() => insightsFromRecordsets(binding, defaultFilters(), sets)).toThrow('integrity');
  });
  it('rejects unsafe counts, cross-currency results, and silently clipped result collections', () => {
    const unsafe = fixture(); unsafe[4][0].sessions = '9007199254740992';
    expect(() => insightsFromRecordsets(binding, defaultFilters(), unsafe)).toThrow();
    expect(() => insightsFromRecordsets(binding, parseInsightsFilters('{"currency":"USD"}'), fixture())).toThrow();
    expect(() => insightsFromRecordsets(binding, defaultFilters(), fixture().slice(0, 9))).toThrow();
  });
  it.each([[1, 33], [2, 51], [3, 129], [5, 367], [6, 601], [7, 13], [8, 51]])
    ('fails closed for oversized recordset %i', (index, length) => {
      const sets = fixture(); sets[index] = Array.from({ length }, () => ({ ...sets[index][0] }));
      expect(() => insightsFromRecordsets(binding, defaultFilters(), sets)).toThrow();
    });
  it('rejects duplicate buckets and money/session totals that do not reconcile', () => {
    const duplicate = fixture(); duplicate[6].push({ ...duplicate[6][0] });
    expect(() => insightsFromRecordsets(binding, defaultFilters(), duplicate)).toThrow();
    const fanout = fixture(); fanout[8][0].booked_minor = '9007199254740993123456790';
    expect(() => insightsFromRecordsets(binding, defaultFilters(), fanout)).toThrow();
    const sessions = fixture(); sessions[5][0].sessions = '3';
    expect(() => insightsFromRecordsets(binding, defaultFilters(), sessions)).toThrow();
  });
  it.each([-0.1, 100.1, Infinity, 'not-progress', ''])('rejects invalid progress %s', value => {
    const sets = fixture(); sets[7][0].average_progress = value;
    expect(() => insightsFromRecordsets(binding, defaultFilters(), sets)).toThrow();
  });
  it('keeps missing progress nullable and distinguishes Gold lineage from live source connections', () => {
    const sets = fixture(); sets[7][0].average_progress = null;
    const result = insightsFromRecordsets(binding, defaultFilters(), sets);
    expect(result.titles[0].averageProgress).toBeNull();
    expect(result.sources.find(source => source.name === 'SAP')).toEqual({ name: 'SAP', state: 'not-published',
      detail: 'Local prospective contract only; no published SAP tables, invoices, revenue or margin are included.', tables: [] });
    expect(result.sources.filter(source => source.name !== 'SAP').every(source => source.detail.includes('not a direct source connectivity check'))).toBe(true);
    expect(result.sources.find(source => source.name === 'Salesforce')?.tables).toContain('gold.fact_customer_consent');
    expect(JSON.stringify(result)).not.toContain('sql_server');
  });
});

describe('one read-only, caller-authorized runtime batch', () => {
  it('opens/closes exactly one Gold pool and runs one batch for the whole dashboard', async () => {
    await readGoldInsights(binding, 'test-token', '{}');
    expect(calls.pools).toBe(1); expect(calls.connections).toBe(1); expect(calls.closes).toBe(1);
    expect(calls.queries).toEqual([GOLD_INSIGHTS_QUERY]);
    expect(calls.inputs.from_date).toBeNull(); expect(calls.inputs.to_date).toBeNull();
    expect(GOLD_INSIGHTS_QUERY).toContain('SET TRANSACTION ISOLATION LEVEL SNAPSHOT');
    expect(GOLD_INSIGHTS_QUERY).not.toMatch(/\b(?:INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|GRANT)\b/i);
  });
  it.each(['connection', 'query', 'mapping', 'cleanup'])('closes resources and sanitizes %s failures', async stage => {
    const secret = new Error('sensitive-server token=do-not-log');
    if (stage === 'connection') calls.connectError = secret;
    if (stage === 'query') calls.queryError = secret;
    if (stage === 'mapping') calls.sets = [];
    if (stage === 'cleanup') calls.closeError = secret;
    await expect(readGoldInsights(binding, 'test-token', '{}')).rejects.toThrow('No operational fallback');
    expect(calls.closes).toBe(1);
  });
  it('reuses bounded exponential connection retry, without replaying a SQL batch', async () => {
    vi.useFakeTimers();
    calls.connectError = Object.assign(new Error('temporary'), { code: 'ETIMEOUT' });
    const result = readGoldInsights(binding, 'test-token', '{}').catch(error => error as Error);
    await vi.runAllTimersAsync();
    expect(await result).toBeInstanceOf(Error);
    expect(calls.connections).toBe(3); expect(calls.queries).toHaveLength(0); expect(calls.closes).toBe(1);
  });
  it('refuses an unverified binding and never substitutes operational SQL', async () => {
    await expect(readGoldInsights({ ...binding, verified: false }, 'test-token', '{}')).rejects.toThrow('not verified');
    expect(calls.pools).toBe(0);
  });
  it('registers a caller-data-authorized handler with a literal SQL audience and pure return DTO import', () => {
    const source = readFileSync(new URL('../../apps/cockpit/rayfin/functions/src/function_app.ts', import.meta.url), 'utf8');
    expect(source).toMatch(/udf\.func\('businessInsights', async \(filtersJson: string,\s*ctx: RayfinContext<AppSchema, AudienceType.Sql>\): Promise<GoldInsights>/);
    expect(source).toContain('readGoldInsights(await analytics(ctx), ctx.Tokens.Sql, filtersJson)');
    expect(source).toContain("import type { GoldInsights } from './gold-insights-contract.js'");
    expect(source).toContain('ctx.getDataClient().AnalyticsBinding.select');
  });
  it('keeps the verification helper read-only and distinguishes baseline evidence from new-backend verification', () => {
    const source = readFileSync(new URL('../../apps/cockpit/tools/verify-insights.mjs', import.meta.url), 'utf8');
    const query = source.match(/export const COMPARISON_QUERY = `([\s\S]*?)`;/)?.[1] ?? '';
    expect(query).toContain('WHERE EXISTS (SELECT 1 FROM selected f WHERE f.order_id=p.order_id');
    expect(query).not.toMatch(/\b(?:INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|GRANT)\b/i);
    expect(source).toContain("evidence.status = 'baseline-only'");
    expect(source).toContain('new_backend_executed: false, independent_sql_compared: false');
    expect(source).toContain("{ silentOnly: true }");
    expect(source).not.toMatch(/placeOrder\.invoke|startPlayback\.invoke|initialize-access|extend-operator/);
  });
  it('uses publication only as a serving gate, not a producer-run filter or a recent-row sample', () => {
    expect(GOLD_INSIGHTS_QUERY).toContain('FROM gold.publication ORDER BY completed_at DESC,run_id');
    expect(GOLD_INSIGHTS_QUERY).not.toMatch(/\b(?:f|p|c|v|t)\.run_id|JOIN\s+gold\.publication|TOP\s*\(1000\)/i);
    expect(GOLD_INSIGHTS_QUERY).not.toMatch(/(?:FROM|JOIN)\s+(?:dbo\.|silver\.|sap\.)/i);
    expect(GOLD_INSIGHTS_QUERY).toContain('ORDER BY COUNT_BIG(*) DESC,currency');
    expect(GOLD_INSIGHTS_QUERY).toContain('DATEADD(day,-29,@EndDate)');
  });
});

/* Execute the production cohort CTE against tiny in-memory fixtures. Only the two
   T-SQL date expressions are adapted for SQLite; business joins and predicates are unchanged. */
function cohortDatabase() {
  const db = new DatabaseSync(':memory:');
  db.exec(`ATTACH DATABASE ':memory:' AS gold;
    CREATE TABLE gold.dim_content(content_key TEXT,title TEXT,genre TEXT,duration_seconds INTEGER);
    CREATE TABLE gold.dim_customer(customer_key TEXT);
    CREATE TABLE gold.dim_offer(offer_key TEXT,content_key TEXT,currency TEXT,transaction_type TEXT);
    CREATE TABLE gold.fact_order_line(order_id TEXT,line_number INTEGER,customer_key TEXT,content_key TEXT,offer_key TEXT,
      territory TEXT,currency TEXT,transaction_type TEXT,created_at TEXT,amount_minor INTEGER,first_play_at TEXT);
    CREATE TABLE gold.fact_playback_session(session_id TEXT,order_id TEXT,customer_key TEXT,content_key TEXT,status TEXT,position_seconds INTEGER);
    INSERT INTO gold.dim_content VALUES ('A','Film A','Action',100),('B','Film B','Drama',200),('C','Film C','Drama',0);
    INSERT INTO gold.dim_customer VALUES ('C1'),('C2');
    INSERT INTO gold.dim_offer VALUES ('EA','A','EUR','TVOD'),('EB','B','EUR','EST'),('UA','A','USD','TVOD'),('UC','C','USD','EST');
    INSERT INTO gold.fact_order_line VALUES
      ('O1',1,'C1','A','EA','FR','EUR','TVOD','2026-10-08',100,NULL),
      ('O1',2,'C1','A','EA','FR','EUR','TVOD','2026-10-08',200,NULL),
      ('O1',3,'C1','B','EB','FR','EUR','EST','2026-10-08',400,NULL),
      ('O2',1,'C2','A','UA','US','USD','TVOD','2026-10-08',90000,NULL),
      ('O3',1,'C2','C','UC','US','USD','EST','2026-10-08',1000,NULL);
    INSERT INTO gold.fact_playback_session VALUES
      ('S1','O1','C1','A','COMPLETED',250),('S2','O1','C1','B','PLAYING',100),
      ('wrong-customer','O1','C2','A','COMPLETED',100),('wrong-content','O1','C1','C','COMPLETED',1),
      ('S3','O2','C2','A','PLAYING',20),('S4','O3','C2','C','PLAYING',500);
  `);
  const match = GOLD_INSIGHTS_QUERY.match(/WITH cohort AS \([\s\S]*?FROM gold\.fact_playback_session p[\s\S]*?\n\)/);
  if (!match) throw new Error('Production cohort CTE not found');
  const cte = match[0].replaceAll('CAST(f.created_at AS date)', 'date(f.created_at)')
    .replaceAll('DATEADD(day,1,@EndDate)', "date(@EndDate,'+1 day')");
  const query = (extra: Record<string, string> = {}) => {
    const statement = db.prepare(`${cte} SELECT
      (SELECT COUNT(*) FROM cohort) AS lines,
      (SELECT COUNT(DISTINCT order_id) FROM cohort) AS orders,
      (SELECT COALESCE(SUM(amount_minor),0) FROM cohort) AS money,
      (SELECT COUNT(*) FROM cohort_sessions) AS sessions,
      (SELECT COALESCE(SUM(completed),0) FROM cohort_sessions) AS completed,
      (SELECT AVG(progress) FROM cohort_sessions) AS progress`);
    statement.setReadBigInts(true);
    return statement.get({ '@StartDate': '2026-10-07', '@EndDate': '2026-10-09', '@SelectedCurrency': 'EUR',
      '@territory': '', '@genre': '', '@transaction_type': '', ...extra });
  };
  return { db, query };
}

describe('full-fact cohort join semantics', () => {
  it('counts two same-title lines once for playback and excludes wrong customer/content links', () => {
    const { db, query } = cohortDatabase();
    try { expect(query()).toEqual({ lines: 3n, orders: 1n, money: 700n, sessions: 2n, completed: 1n, progress: 75 }); }
    finally { db.close(); }
  });
  it('isolates currencies and every dimension predicate without converting money', () => {
    const { db, query } = cohortDatabase();
    try {
      expect(query({ '@SelectedCurrency': 'USD' })).toMatchObject({ lines: 2n, orders: 2n, money: 91000n, sessions: 2n, progress: 20 });
      expect(query({ '@genre': 'Action' })).toMatchObject({ lines: 2n, money: 300n, sessions: 1n });
      expect(query({ '@transaction_type': 'EST' })).toMatchObject({ lines: 1n, money: 400n, sessions: 1n });
      expect(query({ '@territory': 'US' })).toMatchObject({ lines: 0n, money: 0n, sessions: 0n });
      expect(query({ '@genre': "Action' OR 1=1--" })).toMatchObject({ lines: 0n, money: 0n, sessions: 0n });
    } finally { db.close(); }
  });
  it('uses order dates for playback, caps latest position, and excludes invalid durations from averages', () => {
    const { db, query } = cohortDatabase();
    try {
      expect(query({ '@StartDate': '2026-10-09' })).toMatchObject({ lines: 0n, sessions: 0n });
      expect(query({ '@genre': 'Action' })).toMatchObject({ progress: 100 });
      expect(query({ '@SelectedCurrency': 'USD', '@transaction_type': 'EST' })).toMatchObject({ sessions: 1n, progress: null });
    } finally { db.close(); }
  });
  it('contains explicit uniqueness, ambiguity and missing-dimension guards before metric selects', () => {
    const { db } = cohortDatabase();
    try {
      db.exec("INSERT INTO gold.dim_content VALUES ('A','Duplicate A','Action',100)");
      const guard = GOLD_INSIGHTS_QUERY.match(/SELECT content_key FROM gold\.dim_content GROUP BY content_key HAVING COUNT_BIG\(\*\)>1/)?.[0];
      expect(guard).toBeDefined();
      expect(db.prepare(guard!.replace('COUNT_BIG', 'COUNT')).all()).toHaveLength(1);
      expect(GOLD_INSIGHTS_QUERY.indexOf("THROW 51011")).toBeLessThan(GOLD_INSIGHTS_QUERY.indexOf('WITH cohort AS'));
      expect(GOLD_INSIGHTS_QUERY).toContain('GROUP BY order_id,line_number HAVING COUNT_BIG(*)>1');
      expect(GOLD_INSIGHTS_QUERY).toContain('k.order_id=p.order_id AND k.customer_key=p.customer_key AND k.content_key=p.content_key');
      expect(GOLD_INSIGHTS_QUERY).toContain("THROW 51013, 'Ambiguous playback to order-line cohort'");
      expect(GOLD_INSIGHTS_QUERY).toContain('o.currency=f.currency AND o.transaction_type=f.transaction_type');
      expect(GOLD_INSIGHTS_QUERY).toContain('FROM title_orders c LEFT JOIN title_sessions s');
    } finally { db.close(); }
  });
  it('does not join consent/touch rows to money and requires explicit conversion order/customer links', () => {
    const cte = GOLD_INSIGHTS_QUERY.match(/WITH cohort AS \([\s\S]*?FROM gold\.fact_playback_session p[\s\S]*?\n\)/)?.[0] ?? '';
    expect(cte).not.toMatch(/fact_customer_consent|fact_campaign_touch|fact_campaign_conversion/);
    expect(GOLD_INSIGHTS_QUERY).toContain("WHERE LOWER(purpose)='marketing' AND effective_at<=@PublishedAt");
    expect(GOLD_INSIGHTS_QUERY).toContain('PARTITION BY customer_key,LOWER(purpose),channel ORDER BY effective_at DESC,source_sequence DESC');
    expect(GOLD_INSIGHTS_QUERY).toContain('c.order_id=v.order_id AND c.customer_key=v.customer_key');
    expect(GOLD_INSIGHTS_QUERY).toContain('s.current_rank=1 AND s.granted=1');
  });
});
