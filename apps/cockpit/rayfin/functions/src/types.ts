/**
 * Function schema types for RayfinClient.
 *
 * AUTO-GENERATED — do not edit manually.
 * Re-generated automatically when function source files change.
 *
 * If this file is not updating automatically, run:
 *   rayfin dev functions apply
 *
 * The schema is a closed object type: only the function names listed
 * below are accepted by RayfinClient.functions.<name>.invoke(...).
 * Adding, renaming, or changing the signature of a udf.func() call
 * regenerates this file and surfaces type errors at every consumer.
 *
 * IMPORTANT: This file must NOT import any Node.js packages — it is
 * resolved by the frontend app's TypeScript compiler.
 */

export type AppFunctionsSchema = {
  capabilities: {
    input: Record<string, never>;
    output: { can_operate: boolean; reason: string };
  };
  health: {
    input: Record<string, never>;
    output: { database: string; functions: string; outbox_pending: number; broker: string };
  };
  operationalOrders: {
    input: { ordersPage: number; playbackPage: number };
    output: { rentals: { id: string; order_id: string; customer_key: string; offer_key: string; status: string; amount_minor: number; currency: string; created_at: Date; start_deadline?: undefined | Date; first_play_at?: undefined | Date; expires_at?: undefined | Date }[]; playback: { id: string; session_id: string; order_id: string; content_key: string; customer_key: string; position_seconds: number; status: string }[]; orders: { page: number; pageSize: number; total: number }; sessions: { page: number; pageSize: number; total: number } };
  };
  businessDashboard: {
    input: Record<string, never>;
    output: { source: { name: string; workspace_id: string; item_id: string; views: string[] }; state: 'ready' | 'empty' | 'unpublished'; freshness: { queried_at: string; published_at: null | string; publication_run_id: null | string; order_lines: null | string }; commercial: { currency: string; transaction_type: string; current_order_lines: string; booked_amount_minor: string; booked_amount_decimal: string }[]; playback: { content_key: string; status: string; current_sessions: string; furthest_position_seconds: string }[]; campaigns: { campaign_key: string; recorded_conversions: string }[]; dimensions: { customers: string; content: string } };
  };
  businessViews: {
    input: Record<string, never>;
    output: { dashboard: { source: { name: string; workspace_id: string; item_id: string; views: string[] }; state: 'ready' | 'empty' | 'unpublished'; freshness: { queried_at: string; published_at: null | string; publication_run_id: null | string; order_lines: null | string }; commercial: { currency: string; transaction_type: string; current_order_lines: string; booked_amount_minor: string; booked_amount_decimal: string }[]; playback: { content_key: string; status: string; current_sessions: string; furthest_position_seconds: string }[]; campaigns: { campaign_key: string; recorded_conversions: string }[]; dimensions: { customers: string; content: string } } | { source: { name: string; workspace_id: string; item_id: string; views: string[] }; freshness: { queried_at: string; published_at: null | string; publication_run_id: null | string; order_lines: null | string } } & { scope: 'catalog'; state: 'ready' | 'unpublished'; commercial: null; playback: null; campaigns: null; dimensions: null }; catalog: { [k: string]: null | string }[]; customers: { [k: string]: null | string }[]; offers: { [k: string]: null | string }[]; orders: { [k: string]: null | string }[]; sessions: { [k: string]: null | string }[]; campaigns: { [k: string]: null | string }[]; window: { orders: number; sessions: number; references: number } };
  };
  businessInsights: {
    input: { filtersJson: string };
    output: { state: 'ready' | 'empty' | 'unpublished'; freshness: { queried_at: string; published_at: null | string; publication_run_id: null | string }; source: { name: string; workspace_id: string; item_id: string }; filters: { from: string; to: string; territory: string; genre: string; transactionType: '' | 'TVOD' | 'EST'; currency: string }; options: { from: null | string; to: null | string; territories: string[]; genres: string[]; currencies: string[]; currencyMinorExponents: { currency: string; minorExponent: number }[] }; scope: { orders: 'created-at-cohort'; sessions: 'latest-recorded-state-for-cohort-orders'; money: 'booked-order-value-not-recognized-revenue' | 'nominal-booked-order-value-no-fx'; contactableCustomers: 'cohort-customers-current-marketing-consent-any-channel'; campaigns: 'selected-territory-all-dates'; touches: 'cohort-customer-touches-in-date-range'; conversions: 'explicit-conversions-for-cohort-orders' }; summary: { orders: number; orderLines: number; customers: number; titles: number; bookedMinor: string; sessions: number; playedOrders: number; completedSessions: number }; daily: { date: string; orders: number; bookedMinor: string; sessions: number }[]; heatmap: { territory: string; genre: string; orders: number; bookedMinor: string }[]; titles: { contentKey: string; title: string; genre: string; orders: number; bookedMinor: string; sessions: number; completedSessions: number; averageProgress: null | number }[]; territories: { territory: string; orders: number; customers: number; bookedMinor: string; sessions: number }[]; audience: { customerCount: number; contactableCustomers: null | number; campaigns: number; touches: null | number; conversions: null | number }; sources: { name: 'Oracle' | 'Salesforce' | 'RTI' | 'SAP'; state: 'published' | 'not-published'; detail: string; tables: string[] }[] };
  };
  getCampaignImpact: {
    input: { filtersJson: string };
    output: { source: { name: string; workspace_id: string; item_id: string; view: string }; state: 'ready' | 'empty' | 'unpublished'; freshness: { queried_at: string; published_at: null | string; publication_run_id: null | string }; filters: { analysisMode: 'recorded' | 'post_contact'; from: string; to: string; territory: string; campaignKey: string; currency: string }; options: { currencies: { currency: string; minor_exponent: number }[]; territories: string[]; campaigns: { campaign_key: string; name: string }[] }; summary: { contacted_customers: number; touches: number; buyers: number; orders: number; played_orders: number; engaged_orders: number; unknown_duration_orders: number; booked_minor: string; engaged_minor: string; not_started_minor: string; engaged_per_100_minor: null | string }; campaigns: ({ contacted_customers: number; touches: number; buyers: number; orders: number; played_orders: number; engaged_orders: number; unknown_duration_orders: number; booked_minor: string; engaged_minor: string; not_started_minor: string; engaged_per_100_minor: null | string } & { campaign_key: string; name: string })[]; trend: ({ contacted_customers: number; touches: number; buyers: number; orders: number; played_orders: number; engaged_orders: number; unknown_duration_orders: number; booked_minor: string; engaged_minor: string; not_started_minor: string; engaged_per_100_minor: null | string } & { date: string })[]; titles: { content_key: string; title: string; genre: string; distributor: string; orders: number; engaged_orders: number; booked_minor: string; engaged_minor: string }[]; coverage: { unattributed_orders: number; linked_without_touch_orders: number; ambiguous_orders: number; excluded_minor: string }; methodology: { attribution: 'recorded_only' | 'observed_post_contact'; cohort: 'first_campaign_contact'; contact_window_days: null; engagement_percent: number; coverage_dates: 'order_created'; coverage_campaigns: 'all' } };
  };
  businessPage: {
    input: { view: string };
    output: { dashboard: { source: { name: string; workspace_id: string; item_id: string; views: string[] }; state: 'ready' | 'empty' | 'unpublished'; freshness: { queried_at: string; published_at: null | string; publication_run_id: null | string; order_lines: null | string }; commercial: { currency: string; transaction_type: string; current_order_lines: string; booked_amount_minor: string; booked_amount_decimal: string }[]; playback: { content_key: string; status: string; current_sessions: string; furthest_position_seconds: string }[]; campaigns: { campaign_key: string; recorded_conversions: string }[]; dimensions: { customers: string; content: string } } | { source: { name: string; workspace_id: string; item_id: string; views: string[] }; freshness: { queried_at: string; published_at: null | string; publication_run_id: null | string; order_lines: null | string } } & { scope: 'catalog'; state: 'ready' | 'unpublished'; commercial: null; playback: null; campaigns: null; dimensions: null }; catalog: { [k: string]: null | string }[]; customers: { [k: string]: null | string }[]; offers: { [k: string]: null | string }[]; orders: { [k: string]: null | string }[]; sessions: { [k: string]: null | string }[]; campaigns: { [k: string]: null | string }[]; window: { orders: number; sessions: number; references: number } };
  };
  businessGraph: {
    input: Record<string, never>;
    output: { source: { workspace_id: string; ontology_id: string; graph_model_id: string; gold_item_id: string; verified?: undefined | false | true }; state: 'ready' | 'empty' | 'pending' | 'binding-mismatch'; queried_at: string; generation: number; message: string; nodes: { key: string; type: string; label: string; created_at?: undefined | string; status?: undefined | string; amount_minor?: undefined | number; currency?: undefined | string; position_seconds?: undefined | number }[]; edges: { from: string; to: string; type: string }[]; limit: number; context?: undefined | { playback_limit: number; playback_truncated: boolean; distributor_limit: number; distributors_truncated: boolean } };
  };
  businessGraphSlice: {
    input: { journeyLimit: number };
    output: { source: { workspace_id: string; ontology_id: string; graph_model_id: string; gold_item_id: string; verified?: undefined | false | true }; state: 'ready' | 'empty' | 'pending' | 'binding-mismatch'; queried_at: string; generation: number; message: string; nodes: { key: string; type: string; label: string; created_at?: undefined | string; status?: undefined | string; amount_minor?: undefined | number; currency?: undefined | string; position_seconds?: undefined | number }[]; edges: { from: string; to: string; type: string }[]; limit: number; context?: undefined | { playback_limit: number; playback_truncated: boolean; distributor_limit: number; distributors_truncated: boolean } };
  };
  flixyAsk: {
    input: { question: string; historyJson: string };
    output: { text: string; sources: { label: string; url?: undefined | string }[] };
  };
  placeOrder: {
    input: { input: { customer_key: string; offer_key: string; idempotency_key: string } };
    output: { entity_key: string; event_ids: string[]; status: string };
  };
  startPlayback: {
    input: { input: { order_id: string; idempotency_key: string } };
    output: { entity_key: string; event_ids: string[]; status: string };
  };
  recordProgress: {
    input: { input: { session_id: string; position_seconds: number; idempotency_key: string } };
    output: { entity_key: string; event_ids: string[]; status: string };
  };
  expireRentals: {
    input: { idempotency_key: string };
    output: { entity_key: string; event_ids: string[]; status: string };
  };
  requestControl: {
    input: { input: { type: 'simulate' | 'start' | 'stop' | 'refresh' | 'reload_oracle' | 'reload_salesforce'; limit: number; idempotency_key: string } };
    output: { entity_key: string; event_ids: string[]; status: string };
  };
};
