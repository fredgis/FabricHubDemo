export type CampaignImpactFilters = {
  from: string;
  to: string;
  territory: string;
  campaignKey: string;
  currency: string;
};

export type CampaignImpactMetrics = {
  contacted_customers: number;
  touches: number;
  buyers: number;
  orders: number;
  played_orders: number;
  engaged_orders: number;
  unknown_duration_orders: number;
  booked_minor: string;
  engaged_minor: string;
  not_started_minor: string;
  engaged_per_100_minor: string | null;
};

export type CampaignImpact = {
  source: { name: string; workspace_id: string; item_id: string; view: string };
  state: 'ready' | 'empty' | 'unpublished';
  freshness: { queried_at: string; published_at: string | null; publication_run_id: string | null };
  filters: CampaignImpactFilters;
  options: {
    currencies: { currency: string; minor_exponent: number }[];
    territories: string[];
    campaigns: { campaign_key: string; name: string }[];
  };
  summary: CampaignImpactMetrics;
  campaigns: (CampaignImpactMetrics & { campaign_key: string; name: string })[];
  trend: (CampaignImpactMetrics & { date: string })[];
  titles: {
    content_key: string;
    title: string;
    genre: string;
    distributor: string;
    orders: number;
    engaged_orders: number;
    booked_minor: string;
    engaged_minor: string;
  }[];
  coverage: {
    unattributed_orders: number;
    linked_without_touch_orders: number;
    ambiguous_orders: number;
    excluded_minor: string;
  };
  methodology: {
    attribution: 'recorded_only';
    cohort: 'first_campaign_contact';
    contact_window_days: null;
    engagement_percent: number;
    coverage_dates: 'order_created';
  };
};
