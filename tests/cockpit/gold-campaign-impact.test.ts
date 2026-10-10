// @vitest-environment node
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import { describe, expect, it, vi } from 'vitest';

const calls = vi.hoisted(() => ({ inputs: {} as Record<string, unknown>, query: '', sets: [] as unknown[], closed: false }));
vi.mock('../../apps/cockpit/rayfin/functions/src/gold-dashboard', () => ({
  connectGoldPool: vi.fn(),
  goldPool: vi.fn(() => ({
    close: async () => { calls.closed = true; },
    request: () => {
      const request = {
        input: (name: string, _type: unknown, value: unknown) => { calls.inputs[name] = value; return request; },
        query: async (query: string) => { calls.query = query; return { recordsets: calls.sets }; },
      };
      return request;
    },
  })),
}));
import { campaignFromRecordsets, GOLD_CAMPAIGN_QUERY, parseCampaignFilters, readCampaignImpact } from '../../apps/cockpit/rayfin/functions/src/gold-campaign-impact';
import type { AnalyticsBinding } from '../../apps/cockpit/rayfin/data/schema';

const source = { name: 'MSFlixGold', workspace_id: 'workspace', item_id: 'warehouse' };
const filters = parseCampaignFilters('{}');
type Rows = Record<string, unknown>[][];
function fixture(amount = '9007199254740993'): Rows {
  const metric = { contacted_customers: '2', touches: '3', buyers: '1', orders: '1', played_orders: '1', engaged_orders: '1',
    unknown_duration_orders: '0', booked_minor: amount, engaged_minor: amount, not_started_minor: '0' };
  return [
    [{ run_id: 'publication', completed_at: new Date('2026-10-09T10:00:00Z'), queried_at: new Date('2026-10-09T10:01:00Z'),
      date_from: '2026-10-07', date_to: '2026-10-09', currency: 'EUR' }],
    [{ currency: 'EUR', minor_exponent: 2 }, { currency: 'USD', minor_exponent: 2 }], [{ territory: 'FR' }],
    [{ campaign_key: 'M1', name: 'Campaign one' }], [{ ...metric }],
    [{ ...metric, campaign_key: 'M1', name: 'Campaign one' }], [{ ...metric, date: '2026-10-07' }],
    [{ content_key: 'A', title: 'Film A', genre: 'Animation', distributor: 'Distributor', orders: '1', engaged_orders: '1',
      booked_minor: amount, engaged_minor: amount }],
    [{ unattributed_orders: '3', linked_without_touch_orders: '1', ambiguous_orders: '1', excluded_minor: '500' }],
  ];
}

describe('Campaign Impact API boundary', () => {
  it('validates dates, currency isolation and bounded JSON before SQL', () => {
    expect(filters).toEqual({ analysisMode: 'recorded', from: '', to: '', currency: '', territory: '', campaignKey: '' });
    expect(parseCampaignFilters('{"analysisMode":"post_contact"}').analysisMode).toBe('post_contact');
    expect(() => parseCampaignFilters('{"analysisMode":"last_touch"}')).toThrow();
    for (const input of ['null', '[]', 'broken', '{"other":1}', '{"currency":"*"}', '{"currency":"eur"}',
      '{"from":"2026-02-29"}', '{"from":"2026-10-09","to":"2026-10-08"}', '{"from":"2024-01-01","to":"2025-01-01"}',
      '{"campaignKey":1}', JSON.stringify({ territory: 'x'.repeat(2050) })]) expect(() => parseCampaignFilters(input)).toThrow();
    expect(parseCampaignFilters('{"from":"2024-01-01","to":"2024-12-31"}').to).toBe('2024-12-31');
    expect(parseCampaignFilters('{"currency":"ALL"}').currency).toBe('ALL'); // ISO Albanian lek, not an aggregate marker.
  });
  it('keeps money exact, computes the per-100 ratio with integer rounding, and exposes no connection metadata', () => {
    const result = campaignFromRecordsets({ ...source, sql_server: 'not-for-browser' } as typeof source, filters, fixture());
    expect(result.summary.engaged_per_100_minor).toBe('450359962737049650');
    expect(result.summary.booked_minor).toBe('9007199254740993');
    expect(Object.keys(result.source)).toEqual(['name', 'workspace_id', 'item_id', 'view']);
    expect(result.trend).toHaveLength(3);
    expect(result.trend[1].engaged_per_100_minor).toBeNull();
    const thirds = fixture('1');
    for (const index of [4, 5, 6]) thirds[index][0].contacted_customers = '3';
    expect(campaignFromRecordsets(source, filters, thirds).summary.engaged_per_100_minor).toBe('33');
  });
  it('keeps coverage visible for an empty cohort, returns null for a zero denominator, and gates unpublished data', () => {
    const sets = fixture('0');
    for (const key of Object.keys(sets[4][0])) sets[4][0][key] = '0';
    for (const index of [5, 6, 7]) sets[index] = [];
    const empty = campaignFromRecordsets(source, filters, sets);
    expect(empty.state).toBe('empty'); expect(empty.summary.engaged_per_100_minor).toBeNull();
    expect(empty.coverage.unattributed_orders).toBe(3);
    sets[0][0].run_id = null;
    const unpublished = campaignFromRecordsets(source, filters, sets);
    expect(unpublished.state).toBe('unpublished'); expect(unpublished.coverage.unattributed_orders).toBe(0);
    expect(unpublished.options.currencies).toEqual([]); expect(unpublished.trend).toEqual([]);
  });
  it('never sums distinct customers or buyers across campaign groups', () => {
    const sets = fixture('200');
    sets[3].push({ campaign_key: 'M2', name: 'Campaign two' });
    sets[4][0] = { ...sets[4][0], touches: '6', orders: '2', played_orders: '2', engaged_orders: '2' };
    sets[5] = [
      { ...sets[5][0], booked_minor: '100', engaged_minor: '100' },
      { ...sets[5][0], campaign_key: 'M2', name: 'Campaign two', booked_minor: '100', engaged_minor: '100' },
    ];
    sets[6] = [{ ...sets[4][0], date: '2026-10-07' }];
    const result = campaignFromRecordsets(source, filters, sets);
    expect(result.summary.contacted_customers).toBe(2); expect(result.summary.buyers).toBe(1);
    expect(result.campaigns.reduce((sum, r) => sum + r.contacted_customers, 0)).toBe(4);
    expect(result.summary.engaged_per_100_minor).toBe('10000');
  });
  it('rejects unsafe money, impossible engagement, cross-currency results and truncated or multiplied totals', () => {
    for (const value of [9007199254740992, '1.2', '-1', null]) {
      const sets = fixture(); sets[4][0].booked_minor = value;
      expect(() => campaignFromRecordsets(source, filters, sets)).toThrow();
    }
    const engagement = fixture(); engagement[4][0].engaged_orders = '2';
    expect(() => campaignFromRecordsets(source, filters, engagement)).toThrow();
    const fanout = fixture(); fanout[6][0].engaged_minor = '0';
    expect(() => campaignFromRecordsets(source, filters, fanout)).toThrow();
    const bounded = fixture(); bounded[3] = Array.from({ length: 201 }, () => ({ campaign_key: 'M1', name: 'Campaign' }));
    expect(() => campaignFromRecordsets(source, filters, bounded)).toThrow();
    expect(() => campaignFromRecordsets(source, parseCampaignFilters('{"currency":"USD"}'), fixture())).toThrow();
    expect(() => campaignFromRecordsets(source, filters, fixture().slice(0, 8))).toThrow();
  });
  it('uses typed SQL parameters, the published view and one snapshot; closes the pool', async () => {
    calls.sets = fixture(); calls.closed = false;
    const campaignKey = "campaign' OR 1=1--";
    await readCampaignImpact(source as AnalyticsBinding, 'test-only', JSON.stringify({ campaignKey, currency: 'EUR' }));
    expect(calls.inputs.campaign_key).toBe(campaignKey); expect(calls.query).not.toContain(campaignKey);
    expect(calls.query).toContain('SET TRANSACTION ISOLATION LEVEL SNAPSHOT');
    expect(calls.query).toContain('FROM gold.campaign_engaged_revenue'); expect(calls.closed).toBe(true);
    expect(calls.query).not.toMatch(/(?:FROM|JOIN)\s+(dbo|silver|sap)\./i);
    expect(calls.inputs.analysis_mode).toBe('recorded');
    const observed = await readCampaignImpact(source as AnalyticsBinding, 'test-only', '{"analysisMode":"post_contact"}');
    expect(calls.inputs.analysis_mode).toBe('post_contact');
    expect(observed.source.view).toBe('gold.campaign_post_contact_revenue');
    expect(observed.methodology.attribution).toBe('observed_post_contact');
    expect(observed.methodology.coverage_campaigns).toBe('all');
    const recorded = campaignFromRecordsets(source, filters, fixture());
    expect(recorded.source.view).toBe('gold.campaign_engaged_revenue');
    expect(recorded.methodology.attribution).toBe('recorded_only');
  });
});

function database() {
  const db = new DatabaseSync(':memory:');
  db.exec(`ATTACH DATABASE ':memory:' AS gold;
    CREATE TABLE gold.dim_customer(customer_key TEXT,territory TEXT);
    CREATE TABLE gold.dim_content(content_key TEXT,title TEXT,genre TEXT,duration_seconds INTEGER,distributor_key TEXT);
    CREATE TABLE gold.dim_distributor(distributor_key TEXT,name TEXT);
    CREATE TABLE gold.commercial_status(status TEXT);
    CREATE TABLE gold.fact_campaign_touch(campaign_key TEXT,customer_key TEXT,occurred_at TEXT);
    CREATE TABLE gold.fact_campaign_conversion(order_id TEXT,customer_key TEXT,campaign_key TEXT);
    CREATE TABLE gold.fact_order_line(order_id TEXT,line_number INTEGER,customer_key TEXT,content_key TEXT,currency TEXT,amount_minor INTEGER,
      created_at TEXT,campaign_key TEXT,first_play_at TEXT,status TEXT,transaction_type TEXT);
    CREATE TABLE gold.fact_playback_session(order_id TEXT,customer_key TEXT,content_key TEXT,position_seconds INTEGER);
    INSERT INTO gold.dim_customer VALUES ('C1','FR'),('C2','FR'),('C3','BE');
    INSERT INTO gold.dim_content VALUES ('A','Film A','Animation',100,'D'),('B','Film B','Animation',NULL,'D');
    INSERT INTO gold.dim_distributor VALUES ('D','Distributor');
    INSERT INTO gold.commercial_status VALUES ('ACTIVE');
    INSERT INTO gold.fact_campaign_touch VALUES ('M1','C1','2026-10-07'),('M1','C1','2026-10-09'),('M1','C2','2026-10-07'),
      ('M2','C1','2026-10-06'),('M2','C2','2026-10-09');
    INSERT INTO gold.fact_order_line VALUES
      ('O1',1,'C1','A','EUR',100,'2026-10-08','M1',NULL,'ACTIVE','TVOD'),
      ('O2',1,'C1','A','EUR',200,'2026-10-08','M1',NULL,'ACTIVE','TVOD'),
      ('O3',1,'C2','A','EUR',300,'2026-10-08',NULL,NULL,'ACTIVE','TVOD'),
      ('O4',1,'C2','A','EUR',400,'2026-10-08','M2',NULL,'ACTIVE','TVOD'),
      ('O5',1,'C3','A','EUR',500,'2026-10-08','M1',NULL,'ACTIVE','TVOD'),
      ('O6',1,'C1','B','EUR',600,'2026-10-08','M1',NULL,'ACTIVE','TVOD'),
      ('O7',1,'C1','A','USD',700,'2026-10-08','M1',NULL,'ACTIVE','TVOD'),
      ('O8',1,'C1','A','EUR',800,'2026-10-08','M1',NULL,'ACTIVE','TVOD'),
      ('O9',1,'C1','A','EUR',900,'2026-10-08','M1',NULL,'CANCELLED','TVOD');
    INSERT INTO gold.fact_campaign_conversion VALUES ('O1','C1','M1'),('O1','C1','M1'),('O2','C1','M2');
    INSERT INTO gold.fact_playback_session VALUES ('O1','C1','A',50),('O1','C1','A',80),('O1','C2','A',100),
      ('O6','C1','B',10000),('O7','C1','A',80);
  `);
  const views = readFileSync(new URL('../../fabric/gold/kpis.sql', import.meta.url), 'utf8').split('-- @batch')
    .filter(s => /CREATE OR ALTER VIEW gold\.campaign_(engaged|post_contact)_revenue AS/.test(s));
  for (const sql of views) {
    // Only dialect spelling changes; the deployed joins, grain and matching predicates stay intact.
    const view = sql.replace('CREATE OR ALTER VIEW', 'CREATE VIEW').replaceAll('COUNT_BIG(', 'COUNT(')
      .replaceAll('CAST(f.created_at AS date)', 'date(f.created_at)')
      .replaceAll('CAST(a.first_contact_at AS date)', 'date(a.first_contact_at)')
      .replaceAll('CAST(o.first_contact_at AS date)', 'date(o.first_contact_at)')
      .replaceAll('CAST(m.first_contact_at AS date)', 'date(m.first_contact_at)');
    db.exec(view);
  }
  return db;
}

describe('three-source Gold view semantics', () => {
  it('reports actual post-contact purchases when explicit attribution is absent, without changing the strict view', () => {
    const db = database();
    try {
      db.exec(`UPDATE gold.fact_order_line SET campaign_key=NULL; DELETE FROM gold.fact_campaign_conversion;
        INSERT INTO gold.fact_playback_session VALUES ('O3','C2','A',79),('O3','C2','A',80);`);
      expect(db.prepare("SELECT COUNT(*) AS n FROM gold.campaign_engaged_revenue WHERE attribution_status='recorded'").get()?.n).toBe(0);
      expect(db.prepare(`SELECT order_id,campaign_key,amount_minor,engaged,cohort_date
        FROM gold.campaign_post_contact_revenue WHERE attribution_status='post_contact' ORDER BY order_id`).all()).toEqual([
        { order_id: 'O3', campaign_key: 'M1', amount_minor: 300, engaged: 1, cohort_date: '2026-10-07' },
        { order_id: 'O4', campaign_key: 'M1', amount_minor: 400, engaged: 0, cohort_date: '2026-10-07' },
      ]);
      const cte = GOLD_CAMPAIGN_QUERY.match(/WITH cohort AS \([\s\S]*?\n\)/)![0];
      const statement = db.prepare(`${cte} SELECT COUNT(DISTINCT CASE WHEN record_kind='contact' THEN customer_key END) AS audience,
        COUNT(DISTINCT order_id) AS orders, SUM(amount_minor) AS booked,
        SUM(CASE WHEN engaged=1 THEN amount_minor ELSE 0 END) AS engaged FROM cohort`);
      const params = { '@StartDate': '2026-10-07', '@EndDate': '2026-10-07', '@SelectedCurrency': 'EUR',
        '@territory': '', '@campaign_key': '', '@analysis_mode': 'post_contact' };
      // Purchase on Oct 8 belongs to the Oct 7 contact cohort, even when To is Oct 7.
      expect(statement.get(params)).toEqual({ audience: 2, orders: 2, booked: 700, engaged: 300 });
      expect(statement.get({ ...params, '@campaign_key': 'M1' })).toEqual({ audience: 2, orders: 2, booked: 700, engaged: 300 });
      expect(statement.get({ ...params, '@analysis_mode': 'recorded' })).toEqual({ audience: 2, orders: 0, booked: 0, engaged: 0 });
      expect(statement.get({ ...params, '@SelectedCurrency': 'USD' })).toEqual({ audience: 2, orders: 0, booked: 0, engaged: 0 });
    } finally { db.close(); }
  });
  it('excludes multi-campaign exposure before filtering and compares full purchase timestamps', () => {
    const db = database();
    try {
      db.exec(`INSERT INTO gold.fact_campaign_touch VALUES ('M3','C3','2026-10-08T12:00:00');
        UPDATE gold.fact_order_line SET created_at='2026-10-08T11:59:59' WHERE order_id='O5';`);
      expect(db.prepare("SELECT attribution_status,campaign_key FROM gold.campaign_post_contact_revenue WHERE order_id='O1'").get())
        .toEqual({ attribution_status: 'ambiguous', campaign_key: null });
      expect(db.prepare("SELECT attribution_status FROM gold.campaign_post_contact_revenue WHERE order_id='O5'").get()?.attribution_status)
        .toBe('without_contact');
      db.exec("UPDATE gold.fact_order_line SET created_at='2026-10-08T12:00:00' WHERE order_id='O5'");
      expect(db.prepare("SELECT attribution_status,campaign_key FROM gold.campaign_post_contact_revenue WHERE order_id='O5'").get())
        .toEqual({ attribution_status: 'post_contact', campaign_key: 'M3' });
      expect(db.prepare("SELECT order_id,line_number,COUNT(*) AS n FROM gold.campaign_post_contact_revenue WHERE record_kind='order' GROUP BY order_id,line_number HAVING COUNT(*)>1").all()).toEqual([]);
      expect(db.prepare("SELECT COUNT(*) AS n FROM gold.campaign_post_contact_revenue WHERE order_id='O9'").get()?.n).toBe(0);
    } finally { db.close(); }
  });
  it('deduplicates recorded links and playback without multiplying booked value', () => {
    const db = database();
    try {
      expect(db.prepare("SELECT amount_minor,played,engaged,cohort_date FROM gold.campaign_engaged_revenue WHERE order_id='O1'").all())
        .toEqual([{ amount_minor: 100, played: 1, engaged: 1, cohort_date: '2026-10-07' }]);
      expect(db.prepare("SELECT touches,currency,amount_minor FROM gold.campaign_engaged_revenue WHERE record_kind='contact' AND campaign_key='M1' AND customer_key='C1'").get())
        .toEqual({ touches: 2, currency: null, amount_minor: 0 });
    } finally { db.close(); }
  });
  it('keeps ambiguous, absent and post-purchase contacts outside attribution, without inferred last-touch', () => {
    const db = database();
    try {
      const rows = db.prepare("SELECT order_id,attribution_status FROM gold.campaign_engaged_revenue WHERE order_id IN ('O2','O3','O4','O5') ORDER BY order_id").all();
      expect(rows.map(r => r.attribution_status)).toEqual(['ambiguous', 'unattributed', 'without_contact', 'without_contact']);
      expect(db.prepare("SELECT COUNT(*) AS n FROM gold.campaign_engaged_revenue WHERE order_id='O9'").get()?.n).toBe(0);
      expect(db.prepare("SELECT played,engaged,unknown_duration FROM gold.campaign_engaged_revenue WHERE order_id='O6'").get())
        .toEqual({ played: 1, engaged: 0, unknown_duration: 1 });
    } finally { db.close(); }
  });
  it('preserves non-buyers and distinct audience while isolating currencies and first-contact dates', () => {
    const db = database();
    try {
      const cte = GOLD_CAMPAIGN_QUERY.match(/WITH cohort AS \([\s\S]*?\n\)/)![0];
      const statement = db.prepare(`${cte} SELECT COUNT(DISTINCT CASE WHEN record_kind='contact' THEN customer_key END) AS audience,
        COUNT(DISTINCT CASE WHEN record_kind='order' THEN customer_key END) AS buyers,
        SUM(amount_minor) AS booked, SUM(CASE WHEN engaged=1 THEN amount_minor ELSE 0 END) AS engaged,
        SUM(CASE WHEN record_kind='order' AND played=0 THEN amount_minor ELSE 0 END) AS not_started FROM cohort`);
      const params = { '@StartDate': '2026-10-07', '@EndDate': '2026-10-08', '@SelectedCurrency': 'EUR', '@territory': '', '@campaign_key': '', '@analysis_mode': 'recorded' };
      expect(statement.get(params)).toEqual({ audience: 2, buyers: 1, booked: 1500, engaged: 100, not_started: 800 });
      expect(statement.get({ ...params, '@SelectedCurrency': 'USD' })).toEqual({ audience: 2, buyers: 1, booked: 700, engaged: 700, not_started: 0 });
      expect(statement.get({ ...params, '@StartDate': '2026-10-06', '@EndDate': '2026-10-09' })?.audience).toBe(2);
      expect(statement.get({ ...params, '@campaign_key': 'M2' })?.audience).toBe(0);
      expect(statement.get({ ...params, '@territory': 'BE' })?.audience).toBe(0);
    } finally { db.close(); }
  });
});
