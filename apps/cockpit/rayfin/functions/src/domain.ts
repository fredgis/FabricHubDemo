import type { Offer, Rental } from '../../data/schema.js';

export type OrderInput = { customer_key: string; offer_key: string; idempotency_key: string };
export type PlayInput = { order_id: string; idempotency_key: string };
export type ProgressInput = { session_id: string; position_seconds: number; idempotency_key: string };
export type ControlInput = { type: 'simulate' | 'start' | 'stop' | 'refresh' | 'reload_oracle' | 'reload_salesforce';
  limit: number; idempotency_key: string };
export type CommandResult = { entity_key: string; event_ids: string[]; status: string };
export type Capabilities = { can_operate: boolean; reason: string };
export type Health = { database: string; functions: string; outbox_pending: number; broker: string };

export function key(value: string, label: string): string {
  if (typeof value !== 'string' || !/^[a-zA-Z0-9_:./-]{1,128}$/.test(value))
    throw new Error(`Invalid ${label}.`);
  return value;
}

export function canonical(value: unknown): string {
  if (value instanceof Date) return JSON.stringify(value.toISOString());
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object')
    return `{${Object.entries(value).filter(([, v]) => v !== undefined)
      .sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)
      .map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(',')}}`;
  return JSON.stringify(value);
}

export function epoch(value: string | Date | undefined): number {
  return value ? new Date(value).getTime() : NaN;
}

export function assertOperator(grant: { enabled: boolean; expires_at: string | Date } | undefined, now: Date): void {
  if (!grant?.enabled || epoch(grant.expires_at) <= now.getTime()
    || !Number.isFinite(epoch(grant.expires_at)))
    throw new Error('Operator permission required. Viewers cannot issue commands.');
}

export function offerPolicy(offer: Offer): void {
  if (!Number.isSafeInteger(offer.price_minor) || offer.price_minor < 0 || offer.price_minor > 2_147_483_647)
    throw new Error('Offer has invalid integer minor-unit price.');
  if (!/^[A-Z]{3}$/.test(offer.currency)) throw new Error('Offer currency is invalid.');
  if (!['TVOD', 'EST'].includes(offer.transaction_type)) throw new Error('Only TVOD and EST commands are supported.');
  if (offer.transaction_type === 'TVOD' &&
    (![offer.start_window_hours, offer.play_window_hours].every(x => Number.isInteger(x) && x > 0 && x <= 8760)))
    throw new Error('Rental windows must be explicit positive hours, at most one year.');
}

export function deadline(offer: Offer, now: Date): string | undefined {
  offerPolicy(offer);
  return offer.transaction_type === 'TVOD'
    ? new Date(now.getTime() + offer.start_window_hours * 3_600_000).toISOString() : undefined;
}

export function canPlay(order: Rental, offer: Offer, now: Date): void {
  offerPolicy(offer);
  if (!['booked', 'active', 'purchased'].includes(order.status)) throw new Error('Entitlement is not playable.');
  const boundary = order.first_play_at ? order.expires_at : order.start_deadline;
  if (offer.transaction_type === 'TVOD' &&
      (!boundary || !Number.isFinite(epoch(boundary)) || now.getTime() >= epoch(boundary)))
    throw new Error('Rental has expired. Playback cannot start at or after its deadline.');
}

export function isExpired(order: Rental, now: Date): boolean {
  const boundary = order.first_play_at ? order.expires_at : order.start_deadline;
  return ['booked', 'active'].includes(order.status) && !!boundary && epoch(boundary) <= now.getTime();
}

export function controlLimit(type: string, limit: number): void {
  if (!['simulate', 'start', 'stop', 'refresh', 'reload_oracle', 'reload_salesforce'].includes(type))
    throw new Error('Unsupported control.');
  if (!Number.isInteger(limit) || limit < 1 || limit > 100) throw new Error('Command limit must be 1-100.');
  if ((type === 'reload_oracle' || type === 'reload_salesforce') && limit !== 1)
    throw new Error('Source reload limit must be 1.');
}
