/** JSON input accepts a partial filter object; responses always contain resolved filters. */
export type GoldInsightsFilters = {
  /** Inclusive UTC order-created date, YYYY-MM-DD. At most 366 days per request. */
  from: string;
  to: string;
  /** Empty means all published territories, genres, or transaction types. */
  territory: string;
  genre: string;
  transactionType: '' | 'TVOD' | 'EST';
  /** ISO currency, or '*' for ALL currencies (nominal sum, no FX). Empty input keeps the server default. */
  currency: string;
};

export type GoldInsights = {
  state: 'ready' | 'empty' | 'unpublished';
  freshness: {
    queried_at: string;
    published_at: string | null;
    /** Publication identity, not an equality filter on producer fact run_id. */
    publication_run_id: string | null;
  };
  source: { name: string; workspace_id: string; item_id: string };
  filters: GoldInsightsFilters;
  /** Global published options, unaffected by current filters. Bounds fail closed, never sample. */
  options: {
    from: string | null;
    to: string | null;
    territories: string[];
    genres: string[];
    currencies: string[];
    currencyMinorExponents: { currency: string; minorExponent: number }[];
  };
  scope: {
    orders: 'created-at-cohort';
    sessions: 'latest-recorded-state-for-cohort-orders';
    money: 'booked-order-value-not-recognized-revenue' | 'nominal-booked-order-value-no-fx';
    contactableCustomers: 'cohort-customers-current-marketing-consent-any-channel';
    campaigns: 'selected-territory-all-dates';
    touches: 'cohort-customer-touches-in-date-range';
    conversions: 'explicit-conversions-for-cohort-orders';
  };
  summary: {
    orders: number;
    orderLines: number;
    customers: number;
    titles: number;
    /** All bookedMinor fields are exact nonnegative integers, across all order statuses.
     * Single currency: its minor units. ALL ('*'): nominal units scaled by 10,000,
     * using gold.currency minor_exponent before addition, never exchange rates. */
    bookedMinor: string;
    sessions: number;
    playedOrders: number;
    completedSessions: number;
  };
  /** Sessions are assigned to their cohort order's created date, not occurred_at. Zero-filled. */
  daily: { date: string; orders: number; bookedMinor: string; sessions: number }[];
  /** Up to 12 genres ranked by full-cohort booked value, across at most 50 territories. */
  heatmap: { territory: string; genre: string; orders: number; bookedMinor: string }[];
  /** Top 12 by full-cohort booked value. summary.titles discloses the full matching count. */
  titles: {
    contentKey: string;
    title: string;
    genre: string;
    orders: number;
    bookedMinor: string;
    sessions: number;
    completedSessions: number;
    /** Mean latest recorded position / valid content duration, capped at 0..100; not watch time. */
    averageProgress: number | null;
  }[];
  /** All matching territories, maximum 50. No hidden top-N sampling. */
  territories: {
    territory: string;
    orders: number;
    customers: number;
    bookedMinor: string;
    sessions: number;
  }[];
  audience: {
    customerCount: number;
    /** Latest effective marketing consent per customer/purpose/channel; unavailable is null. */
    contactableCustomers: number | null;
    /** Separate scope: published campaigns in selected territory, irrespective of date/currency/genre. */
    campaigns: number;
    /** Touches do not attribute booked money to marketing. */
    touches: number | null;
    conversions: number | null;
  };
  /** Describes published Gold projections, not a live source-connector health check. */
  sources: {
    name: 'Oracle' | 'Salesforce' | 'RTI' | 'SAP';
    state: 'published' | 'not-published';
    detail: string;
    tables: string[];
  }[];
};
