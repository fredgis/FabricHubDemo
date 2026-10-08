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
  businessDashboard: {
    input: Record<string, never>;
    output: { source: { name: string; workspace_id: string; item_id: string; views: string[] }; state: 'ready' | 'empty' | 'unpublished'; freshness: { queried_at: string; published_at: null | string; publication_run_id: null | string; order_lines: null | string }; commercial: { currency: string; transaction_type: string; current_order_lines: string; booked_amount_minor: string; booked_amount_decimal: string }[]; playback: { content_key: string; status: string; current_sessions: string; furthest_position_seconds: string }[]; campaigns: { campaign_key: string; recorded_conversions: string }[]; dimensions: { customers: string; content: string } };
  };
  businessViews: {
    input: Record<string, never>;
    output: { dashboard: { source: { name: string; workspace_id: string; item_id: string; views: string[] }; state: 'ready' | 'empty' | 'unpublished'; freshness: { queried_at: string; published_at: null | string; publication_run_id: null | string; order_lines: null | string }; commercial: { currency: string; transaction_type: string; current_order_lines: string; booked_amount_minor: string; booked_amount_decimal: string }[]; playback: { content_key: string; status: string; current_sessions: string; furthest_position_seconds: string }[]; campaigns: { campaign_key: string; recorded_conversions: string }[]; dimensions: { customers: string; content: string } }; catalog: { [k: string]: null | string }[]; customers: { [k: string]: null | string }[]; offers: { [k: string]: null | string }[]; orders: { [k: string]: null | string }[]; sessions: { [k: string]: null | string }[]; campaigns: { [k: string]: null | string }[]; window: { orders: number; sessions: number; references: number } };
  };
  businessPage: {
    input: { view: string };
    output: { dashboard: { source: { name: string; workspace_id: string; item_id: string; views: string[] }; state: 'ready' | 'empty' | 'unpublished'; freshness: { queried_at: string; published_at: null | string; publication_run_id: null | string; order_lines: null | string }; commercial: { currency: string; transaction_type: string; current_order_lines: string; booked_amount_minor: string; booked_amount_decimal: string }[]; playback: { content_key: string; status: string; current_sessions: string; furthest_position_seconds: string }[]; campaigns: { campaign_key: string; recorded_conversions: string }[]; dimensions: { customers: string; content: string } }; catalog: { [k: string]: null | string }[]; customers: { [k: string]: null | string }[]; offers: { [k: string]: null | string }[]; orders: { [k: string]: null | string }[]; sessions: { [k: string]: null | string }[]; campaigns: { [k: string]: null | string }[]; window: { orders: number; sessions: number; references: number } };
  };
  businessGraph: {
    input: Record<string, never>;
    output: { source: { workspace_id: string; ontology_id: string; graph_model_id: string; gold_item_id: string }; state: 'ready' | 'empty' | 'pending' | 'binding-mismatch'; queried_at: string; generation: number; message: string; nodes: { key: string; type: string; label: string }[]; edges: { from: string; to: string; type: string }[]; limit: number };
  };
  businessGraphSlice: {
    input: { journeyLimit: number };
    output: { source: { workspace_id: string; ontology_id: string; graph_model_id: string; gold_item_id: string }; state: 'ready' | 'empty' | 'pending' | 'binding-mismatch'; queried_at: string; generation: number; message: string; nodes: { key: string; type: string; label: string }[]; edges: { from: string; to: string; type: string }[]; limit: number };
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
    input: { input: { type: 'simulate' | 'start' | 'stop' | 'refresh'; limit: number; idempotency_key: string } };
    output: { entity_key: string; event_ids: string[]; status: string };
  };
};
