import type { GoldInsights } from '../../apps/cockpit/src/services/insights';

export function insightsFixture(overrides: Partial<GoldInsights> = {}): GoldInsights {
  return {
    state: 'ready',
    freshness: { queried_at: '2026-10-09T12:00:00Z', published_at: '2026-10-09T10:00:00Z', publication_run_id: 'test-publication' },
    source: { name: 'MSFlixGold', workspace_id: 'test-workspace', item_id: 'test-warehouse' },
    filters: { from: '2026-10-08', to: '2026-10-09', territory: '', genre: '', transactionType: '', currency: 'EUR' },
    options: { from: '2026-01-01', to: '2026-10-09', territories: ['FR', 'GB'], genres: ['Drama', 'Animation'], currencies: ['EUR', 'GBP'] },
    summary: { orders: 3, orderLines: 3, customers: 2, titles: 1, bookedMinor: '3000', sessions: 2, playedOrders: 2, completedSessions: 1 },
    daily: [
      { date: '2026-10-08', orders: 2, bookedMinor: '2000', sessions: 1 },
      { date: '2026-10-09', orders: 1, bookedMinor: '1000', sessions: 1 },
    ],
    heatmap: [
      { territory: 'FR', genre: 'Drama', orders: 2, bookedMinor: '2000' },
      { territory: 'GB', genre: 'Drama', orders: 1, bookedMinor: '1000' },
    ],
    titles: [{ contentKey: 'test-film', title: 'Fixture film', genre: 'Drama', orders: 3, bookedMinor: '3000', sessions: 2, completedSessions: 1, averageProgress: 50 }],
    territories: [
      { territory: 'FR', orders: 2, customers: 1, bookedMinor: '2000', sessions: 1 },
      { territory: 'GB', orders: 1, customers: 1, bookedMinor: '1000', sessions: 1 },
    ],
    audience: { customerCount: 2, contactableCustomers: 1, campaigns: 1, touches: 2, conversions: null },
    sources: [
      { name: 'Oracle', state: 'published', detail: 'Catalogue and offers', tables: ['gold.dim_content', 'gold.dim_offer'] },
      { name: 'Salesforce', state: 'published', detail: 'Customer context', tables: ['gold.dim_customer'] },
      { name: 'RTI', state: 'published', detail: 'Order and playback facts', tables: ['gold.fact_order_line', 'gold.fact_playback_session'] },
      { name: 'SAP', state: 'not-published', detail: 'Local integration contract only', tables: [] },
    ],
    ...overrides,
  };
}
