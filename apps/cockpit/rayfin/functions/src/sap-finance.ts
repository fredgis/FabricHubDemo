import sql from 'mssql';
import type { AnalyticsBinding } from '../../data/schema.js';
import { withGoldPool } from './gold-connection.js';
import type { SapFinance, SapFinanceBalance, SapFinanceBilling, SapFinanceCharge, SapFinanceCompany, SapFinanceFilters,
  SapFinanceMonth, SapFinanceOpenItem, SapFinanceRights, SapFinanceSubscription } from './sap-finance-contract.js';

const MIN_AS_OF = '2020-01-01';
const MAX_AS_OF = '2035-12-31';
const OPEN_ITEM_LIMIT = 50;

export function todayUtc(now = new Date()): string {
  return now.toISOString().slice(0, 10);
}

/** Validate before opening SQL. Only an as-of date is accepted. */
export function parseSapFinanceFilters(filtersJson: string, now = new Date()): SapFinanceFilters {
  if (typeof filtersJson !== 'string' || filtersJson.length > 256) throw new Error('Finance filters must be a small JSON object.');
  let value: unknown;
  try { value = JSON.parse(filtersJson); } catch { throw new Error('Finance filters must be valid JSON.'); }
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Finance filters must be a JSON object.');
  const input = value as Record<string, unknown>;
  if (Object.keys(input).some(key => key !== 'asOf')) throw new Error('Unsupported Finance filter.');
  const asOf = input.asOf === undefined || input.asOf === '' ? todayUtc(now) : input.asOf;
  if (typeof asOf !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(asOf)) throw new Error('Finance as-of date must be YYYY-MM-DD.');
  const parsed = new Date(`${asOf}T00:00:00.000Z`);
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== asOf) throw new Error('Finance as-of date is not a calendar date.');
  if (asOf < MIN_AS_OF || asOf > MAX_AS_OF) throw new Error(`Finance as-of date must be between ${MIN_AS_OF} and ${MAX_AS_OF}.`);
  return { asOf };
}

/** First month (yyyymm) of the 12-month window ending with the as-of month. */
export function windowStart(asOf: string): number {
  const year = Number(asOf.slice(0, 4)), month = Number(asOf.slice(5, 7));
  const index = year * 12 + month - 1 - 11;
  return Math.floor(index / 12) * 100 + (index % 12) + 1;
}

type Row = Record<string, unknown>;
const num = (value: unknown): number => value === null || value === undefined ? 0 : Number(value);
const optNum = (value: unknown): number | null => value === null || value === undefined ? null : Number(value);
const str = (value: unknown): string => value === null || value === undefined ? '' : String(value).trim();
const optStr = (value: unknown): string | null => value === null || value === undefined || String(value).trim() === '' ? null : String(value).trim();

const QUERIES = {
  companies: `SELECT COMPANYCODE, COMPANYCODENAME, CURRENCY, COUNTRY FROM sap_live.company
    WHERE COMPANYCODE IS NOT NULL ORDER BY COMPANYCODE`,
  months: `SELECT COMPANYCODE, currency, calendar_year, calendar_month,
      SUM(journal_lines) journal_lines,
      SUM(recognized_subscription_revenue) subscription_revenue, SUM(recognized_tvod_revenue) tvod_revenue,
      SUM(recognized_est_revenue) est_revenue, SUM(recognized_total_revenue) total_revenue,
      SUM(content_expense) content_expense, SUM(contribution_after_content_cost_only) contribution,
      SUM(net_bank_movement) net_bank_movement, SUM(net_vat_liability) net_vat_liability,
      SUM(deferred_total_liability) deferred_liability,
      MAX(account_completeness_status) completeness, MAX(native_state_status) state
    FROM sap_live.monthly_finance(@as_of)
    WHERE SOURCELEDGER = '0L' AND calendar_year * 100 + calendar_month BETWEEN @from_month AND @to_month
    GROUP BY COMPANYCODE, currency, calendar_year, calendar_month
    ORDER BY COMPANYCODE, calendar_year, calendar_month`,
  balances: `SELECT COMPANYCODE, currency, receivables_outstanding, payables_outstanding, open_item_rows,
      ISNULL(ar_missing_amount_rows, 0) + ISNULL(ap_missing_amount_rows, 0) missing_amount_rows, native_state_status
    FROM sap_live.balances(@as_of) WHERE COMPANYCODE IS NOT NULL ORDER BY COMPANYCODE`,
  receivables: `SELECT TOP (${OPEN_ITEM_LIMIT}) COMPANYCODE, ACCOUNTINGDOCUMENT, CUSTOMER, CUSTOMER_KEY,
      CONVERT(char(10), POSTINGDATE, 23) posting_date, CONVERT(char(10), NETDUEDATE, 23) due_date,
      COMPANYCODECURRENCY, outstanding_signed amount, DOCUMENTITEMTEXT
    FROM sap_live.ar_open_items(@as_of) ORDER BY NETDUEDATE, ACCOUNTINGDOCUMENT`,
  payables: `SELECT TOP (${OPEN_ITEM_LIMIT}) ap.COMPANYCODE, ap.ACCOUNTINGDOCUMENT, ap.SUPPLIER, s.SUPPLIERNAME,
      CONVERT(char(10), ap.POSTINGDATE, 23) posting_date, CONVERT(char(10), ap.NETDUEDATE, 23) due_date,
      ap.COMPANYCODECURRENCY, ap.outstanding_payable_signed amount, ap.DOCUMENTITEMTEXT
    FROM sap_live.ap_open_items(@as_of) ap
    OUTER APPLY (SELECT TOP 1 SUPPLIERNAME FROM sap_live.supplier s WHERE s.SUPPLIER = ap.SUPPLIER) s
    ORDER BY ap.NETDUEDATE, ap.ACCOUNTINGDOCUMENT`,
  billing: `SELECT COMPANYCODE, CURRENCY, ISNULL(billing_linkage_type, 'unlinked') linkage,
      COUNT(DISTINCT BILLINGDOCUMENT) documents, COUNT(DISTINCT CUSTOMER_KEY) customers,
      SUM(NETAMOUNT) net, SUM(TAXAMOUNT) tax, SUM(GROSSAMOUNT) gross
    FROM sap_live.customer_invoice_item
    WHERE COMPANYCODE IS NOT NULL AND BILLINGDOCUMENTDATE <= @as_of
    GROUP BY COMPANYCODE, CURRENCY, ISNULL(billing_linkage_type, 'unlinked')
    ORDER BY COMPANYCODE, linkage`,
  rights: `SELECT r.CONTRACT_ID, r.SUPPLIER, s.SUPPLIERNAME, r.CURRENCY, r.FIXED_NET, r.REVENUE_SHARE, r.REVENUE_BASIS,
      CONVERT(char(10), r.VALID_FROM, 23) valid_from, CONVERT(char(10), r.VALID_TO_EXCLUSIVE, 23) valid_to_exclusive,
      r.SIMULATION_ONLY
    FROM sap_live.rights_contract r
    OUTER APPLY (SELECT TOP 1 SUPPLIERNAME FROM sap_live.supplier s WHERE s.SUPPLIER = r.SUPPLIER) s
    WHERE r.[Key] <> -1 ORDER BY r.CONTRACT_ID`,
  charges: `SELECT CONTRACT_ID, CONVERT(char(10), PERIOD_START, 23) period_start, CHARGE_TYPE, COMPANYCODE,
      CHARGE_NET, BASIS_NET, RATE
    FROM sap_live.contract_charge WHERE PERIOD_START <= @as_of ORDER BY CONTRACT_ID, PERIOD_START, CHARGE_TYPE`,
  subscriptions: `SELECT SUBSCRIPTION_ID, CUSTOMER_KEY, PLAN_ID, STATUS,
      CONVERT(char(10), SERVICE_FROM, 23) service_from, CONVERT(char(10), SERVICE_TO_EXCLUSIVE, 23) service_to_exclusive,
      MONTHLY_NET, VAT_RATE, CURRENCY,
      CASE WHEN SERVICE_FROM <= @as_of AND (SERVICE_TO_EXCLUSIVE IS NULL OR SERVICE_TO_EXCLUSIVE > @as_of) THEN 1 ELSE 0 END active
    FROM sap_live.subscription_contract WHERE SUBSCRIPTION_ID IS NOT NULL ORDER BY SUBSCRIPTION_ID`,
} as const;

export async function readSapFinance(binding: AnalyticsBinding, token: string, filtersJson: string): Promise<SapFinance> {
  const filters = parseSapFinanceFilters(filtersJson);
  const asOfDate = new Date(`${filters.asOf}T00:00:00.000Z`);
  const toMonth = Number(filters.asOf.slice(0, 4)) * 100 + Number(filters.asOf.slice(5, 7));
  const rows = await withGoldPool(binding, token, async pool => {
    const run = async (text: string) => (await pool.request()
      .input('as_of', sql.Date, asOfDate)
      .input('from_month', sql.Int, windowStart(filters.asOf))
      .input('to_month', sql.Int, toMonth)
      .query<Row>(text)).recordset;
    const entries = await Promise.all(Object.entries(QUERIES).map(async ([key, text]) => [key, await run(text)] as const));
    return Object.fromEntries(entries) as unknown as Record<keyof typeof QUERIES, Row[]>;
  });

  const companies: SapFinanceCompany[] = rows.companies.map(row => ({
    code: str(row.COMPANYCODE), name: str(row.COMPANYCODENAME), currency: str(row.CURRENCY), country: str(row.COUNTRY),
  }));
  const months: SapFinanceMonth[] = rows.months.map(row => ({
    company: str(row.COMPANYCODE), currency: str(row.currency), year: num(row.calendar_year), month: num(row.calendar_month),
    journal_lines: num(row.journal_lines), subscription_revenue: num(row.subscription_revenue), tvod_revenue: num(row.tvod_revenue),
    est_revenue: num(row.est_revenue), total_revenue: num(row.total_revenue), content_expense: num(row.content_expense),
    contribution: num(row.contribution), net_bank_movement: num(row.net_bank_movement), net_vat_liability: num(row.net_vat_liability),
    deferred_liability: num(row.deferred_liability), completeness: str(row.completeness), state: str(row.state),
  }));
  const balances: SapFinanceBalance[] = rows.balances.map(row => ({
    company: str(row.COMPANYCODE), currency: str(row.currency), receivables: num(row.receivables_outstanding),
    payables: num(row.payables_outstanding), open_item_rows: num(row.open_item_rows),
    missing_amount_rows: num(row.missing_amount_rows), state: str(row.native_state_status),
  }));
  const receivables: SapFinanceOpenItem[] = rows.receivables.map(row => ({
    company: str(row.COMPANYCODE), document: str(row.ACCOUNTINGDOCUMENT), party: str(row.CUSTOMER), party_name: null,
    customer_key: optStr(row.CUSTOMER_KEY), posting_date: optStr(row.posting_date), due_date: optStr(row.due_date),
    currency: str(row.COMPANYCODECURRENCY), amount: num(row.amount), text: optStr(row.DOCUMENTITEMTEXT),
  }));
  const payables: SapFinanceOpenItem[] = rows.payables.map(row => ({
    company: str(row.COMPANYCODE), document: str(row.ACCOUNTINGDOCUMENT), party: str(row.SUPPLIER), party_name: optStr(row.SUPPLIERNAME),
    customer_key: null, posting_date: optStr(row.posting_date), due_date: optStr(row.due_date),
    currency: str(row.COMPANYCODECURRENCY), amount: num(row.amount), text: optStr(row.DOCUMENTITEMTEXT),
  }));
  const billing: SapFinanceBilling[] = rows.billing.map(row => ({
    company: str(row.COMPANYCODE), currency: str(row.CURRENCY), linkage: str(row.linkage), documents: num(row.documents),
    customers: num(row.customers), net: num(row.net), tax: num(row.tax), gross: num(row.gross),
  }));
  const charges = new Map<string, SapFinanceCharge[]>();
  for (const row of rows.charges) {
    const id = str(row.CONTRACT_ID);
    const list = charges.get(id) ?? [];
    list.push({ period_start: optStr(row.period_start), type: str(row.CHARGE_TYPE), company: str(row.COMPANYCODE),
      charge_net: num(row.CHARGE_NET), basis_net: optNum(row.BASIS_NET), rate: optNum(row.RATE) });
    charges.set(id, list);
  }
  const rights: SapFinanceRights[] = rows.rights.map(row => ({
    contract_id: str(row.CONTRACT_ID), supplier: str(row.SUPPLIER), supplier_name: optStr(row.SUPPLIERNAME),
    currency: str(row.CURRENCY), fixed_net: optNum(row.FIXED_NET), revenue_share: optNum(row.REVENUE_SHARE),
    revenue_basis: optStr(row.REVENUE_BASIS), valid_from: optStr(row.valid_from), valid_to_exclusive: optStr(row.valid_to_exclusive),
    simulation_only: Boolean(row.SIMULATION_ONLY), charges: charges.get(str(row.CONTRACT_ID)) ?? [],
  }));
  const subscriptions: SapFinanceSubscription[] = rows.subscriptions.map(row => ({
    subscription_id: str(row.SUBSCRIPTION_ID), customer_key: optStr(row.CUSTOMER_KEY), plan_id: optStr(row.PLAN_ID),
    status: optStr(row.STATUS), service_from: optStr(row.service_from), service_to_exclusive: optStr(row.service_to_exclusive),
    monthly_net: optNum(row.MONTHLY_NET), vat_rate: optNum(row.VAT_RATE), currency: optStr(row.CURRENCY), active: num(row.active) === 1,
  }));

  return {
    state: months.length || balances.length || billing.length ? 'ready' : 'empty',
    freshness: { queried_at: new Date().toISOString() },
    source: { name: binding.name, schema: 'sap_live', workspace_id: binding.workspace_id, item_id: binding.item_id },
    filters, companies, months, balances, receivables, payables, billing, rights, subscriptions,
  };
}
