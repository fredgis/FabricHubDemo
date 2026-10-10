import type { CampaignImpact, CampaignImpactMetrics } from '../../apps/cockpit/rayfin/functions/src/gold-campaign-contract';

export function campaignMetrics(overrides: Partial<CampaignImpactMetrics> = {}): CampaignImpactMetrics {
  return {
    contacted_customers: 600, touches: 600, buyers: 0, orders: 0, played_orders: 0, engaged_orders: 0,
    unknown_duration_orders: 0, booked_minor: '0', engaged_minor: '0', not_started_minor: '0', engaged_per_100_minor: '0',
    ...overrides,
  };
}

export function campaignImpactFixture(overrides: Partial<CampaignImpact> = {}): CampaignImpact {
  const campaigns = Array.from({ length: 6 }, (_, index) => ({
    ...campaignMetrics({ contacted_customers: 100, touches: 100 }), campaign_key: `test-campaign-${index + 1}`, name: `Test campaign ${index + 1}`,
  }));
  return {
    source: { name: 'Test Gold', workspace_id: 'test-workspace', item_id: 'test-warehouse', view: 'gold.test_campaign_impact' },
    state: 'ready',
    freshness: { queried_at: '2026-10-09T12:01:00Z', published_at: '2026-10-09T12:00:00Z', publication_run_id: 'test-run' },
    filters: { analysisMode: 'recorded', from: '2026-10-07', to: '2026-10-09', territory: '', campaignKey: '', currency: 'EUR' },
    options: {
      currencies: [{ currency: 'EUR', minor_exponent: 2 }, { currency: 'USD', minor_exponent: 2 }, { currency: 'JPY', minor_exponent: 0 }],
      territories: ['FR', 'US'], campaigns: campaigns.map(({ campaign_key, name }) => ({ campaign_key, name })),
    },
    summary: campaignMetrics(), campaigns, trend: [{ ...campaignMetrics(), date: '2026-10-07' }], titles: [],
    coverage: { unattributed_orders: 1043, ambiguous_orders: 0, linked_without_touch_orders: 0, excluded_minor: '104300' },
    methodology: { attribution: 'recorded_only', cohort: 'first_campaign_contact', contact_window_days: null, engagement_percent: 80, coverage_dates: 'order_created', coverage_campaigns: 'all' },
    ...overrides,
  };
}
