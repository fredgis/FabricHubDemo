/** JSON input accepts a partial filter object; responses always contain resolved filters. */
export type SapFinanceFilters = {
  /** Inclusive as-of date for the SAP live table-valued functions, YYYY-MM-DD. Empty input means today (UTC). */
  asOf: string;
};

export type SapFinanceCompany = { code: string; name: string; currency: string; country: string };

/** One SAP leading-ledger (0L) month per company code, in the company-code currency. Never summed across currencies. */
export type SapFinanceMonth = {
  company: string;
  currency: string;
  year: number;
  month: number;
  journal_lines: number;
  subscription_revenue: number;
  tvod_revenue: number;
  est_revenue: number;
  total_revenue: number;
  content_expense: number;
  contribution: number;
  net_bank_movement: number;
  net_vat_liability: number;
  deferred_liability: number;
  completeness: string;
  state: string;
};

export type SapFinanceBalance = {
  company: string;
  currency: string;
  receivables: number;
  payables: number;
  open_item_rows: number;
  missing_amount_rows: number;
  state: string;
};

export type SapFinanceOpenItem = {
  company: string;
  document: string;
  party: string;
  party_name: string | null;
  /** Salesforce customer key when the SAP customer is mapped. */
  customer_key: string | null;
  posting_date: string | null;
  due_date: string | null;
  currency: string;
  amount: number;
  text: string | null;
};

export type SapFinanceBilling = {
  company: string;
  currency: string;
  linkage: string;
  documents: number;
  customers: number;
  net: number;
  tax: number;
  gross: number;
};

export type SapFinanceCharge = {
  period_start: string | null;
  type: string;
  company: string;
  charge_net: number;
  basis_net: number | null;
  rate: number | null;
};

export type SapFinanceRights = {
  contract_id: string;
  supplier: string;
  supplier_name: string | null;
  currency: string;
  fixed_net: number | null;
  revenue_share: number | null;
  revenue_basis: string | null;
  valid_from: string | null;
  valid_to_exclusive: string | null;
  simulation_only: boolean;
  charges: SapFinanceCharge[];
};

export type SapFinanceSubscription = {
  subscription_id: string;
  customer_key: string | null;
  plan_id: string | null;
  status: string | null;
  service_from: string | null;
  service_to_exclusive: string | null;
  monthly_net: number | null;
  vat_rate: number | null;
  currency: string | null;
  active: boolean;
};

export type SapFinance = {
  state: 'ready' | 'empty';
  freshness: { queried_at: string };
  source: { name: string; schema: 'sap_live'; workspace_id: string; item_id: string };
  filters: SapFinanceFilters;
  companies: SapFinanceCompany[];
  /** Last 12 months up to the as-of month, oldest first. */
  months: SapFinanceMonth[];
  balances: SapFinanceBalance[];
  receivables: SapFinanceOpenItem[];
  payables: SapFinanceOpenItem[];
  billing: SapFinanceBilling[];
  rights: SapFinanceRights[];
  subscriptions: SapFinanceSubscription[];
};
