import type { AppSchema } from '../../rayfin/data/schema';
import { getRayfinClient } from './rayfinClient';

export type Snapshot = {
  content: AppSchema['Content'][]; customers: AppSchema['Customer'][];
  offers: AppSchema['Offer'][]; rentals: AppSchema['Rental'][];
  playback: AppSchema['Playback'][]; outbox: AppSchema['Outbox'][];
  commands: AppSchema['ControlCommand'][]; campaigns: AppSchema['Campaign'][];
  members: AppSchema['CampaignMember'][]; links: AppSchema['IntegrationLink'][];
};

export type Page<T> = { items: T[]; hasNextPage: boolean; endCursor?: string | null };
function paged<T>(query: { after(cursor: string): { executePaginated(): Promise<Page<T>> };
  executePaginated(): Promise<Page<T>> }, cursor?: string): Promise<Page<T>> {
  return cursor ? query.after(cursor).executePaginated() : query.executePaginated();
}
export async function allPages<T>(page: (cursor?: string) => Promise<Page<T>>): Promise<T[]> {
  const rows: T[] = [];
  let cursor: string | undefined;
  for (let i = 0; i < 200; i++) {
    const result = await page(cursor);
    rows.push(...result.items);
    if (!result.hasNextPage) return rows;
    if (!result.endCursor || result.endCursor === cursor) throw new Error('Data pagination did not advance.');
    cursor = result.endCursor;
  }
  throw new Error('Dataset exceeds this view’s safe read limit. No partial KPIs are displayed.');
}

export async function loadSnapshot(): Promise<Snapshot> {
  const data = getRayfinClient().data;
  const [content, customers, offers, rentals, playback, outbox, commands, campaigns, members, links] =
    await Promise.all([
      allPages(c => paged(data.Content.select(['id', 'content_key', 'title', 'release_date', 'duration_seconds',
        'genre', 'image_url', 'source_url', 'license', 'attribution','metadata_license','metadata_date_precision',
        'artwork_available','artwork_license','artwork_source_url','artwork_author']).orderBy({ title: 'asc' }).first(5000), c)),
      allPages(c => paged(data.Customer.select(['id', 'customer_key', 'name', 'territory']).orderBy({ customer_key: 'asc' }).first(5000), c)),
      allPages(c => paged(data.Offer.select(['id', 'offer_key', 'content_key', 'territory', 'currency', 'transaction_type',
        'price_minor', 'start_window_hours', 'play_window_hours']).orderBy({ offer_key: 'asc' }).first(5000), c)),
      allPages(c => paged(data.Rental.select(['id', 'order_id', 'customer_key', 'offer_key', 'status', 'amount_minor', 'currency',
        'created_at', 'start_deadline', 'first_play_at', 'expires_at']).orderBy({ order_id: 'asc' }).first(5000), c)),
      allPages(c => paged(data.Playback.select(['id', 'session_id', 'order_id', 'content_key', 'customer_key',
        'position_seconds', 'status']).orderBy({ session_id: 'asc' }).first(5000), c)),
      data.Outbox.select(['id', 'event_id', 'event_type', 'entity_key', 'source_sequence',
        'occurred_at', 'produced_at', 'run_id', 'correlation_id', 'schema_version', 'published_at'])
        .orderBy({ occurred_at: 'desc' }).first(1000).execute(),
      allPages(c => paged(data.ControlCommand.select(['id', 'idempotency_key', 'type', 'status', 'parameters', 'requested_at',
        'completed_at', 'error']).orderBy({ requested_at: 'desc' }).first(500), c)),
      allPages(c => paged(data.Campaign.select(['id', 'campaign_key', 'name', 'status', 'type', 'start_date',
        'end_date']).orderBy({ campaign_key: 'asc' }).first(500), c)),
      allPages(c => paged(data.CampaignMember.select(['id', 'member_key', 'campaign_key', 'customer_key',
        'status']).orderBy({ member_key: 'asc' }).first(500), c)),
      allPages(c => paged(data.IntegrationLink.select(['id', 'link_key', 'name', 'type', 'url',
        'description']).orderBy({ link_key: 'asc' }).first(500), c)),
    ]);
  return { content, customers, offers, rentals, playback, outbox: outbox as AppSchema['Outbox'][],
    commands, campaigns, members, links };
}

export function money(minor: number, currency: string): string {
  if (!Number.isSafeInteger(minor)) throw new Error('Money must be exact integer minor units.');
  const format = new Intl.NumberFormat('en', { style: 'currency', currency });
  const digits = format.resolvedOptions().maximumFractionDigits ?? 2;
  const exact = BigInt(minor);
  const divisor = 10n ** BigInt(digits);
  const whole = exact / divisor;
  const fraction = ((exact < 0n ? -exact : exact) % divisor).toString().padStart(digits, '0');
  const amount = whole === 0n && exact < 0n ? -0 : whole;
  return format.formatToParts(amount).map(part => part.type === 'fraction' ? fraction : part.value).join('');
}

export function revenueByCurrency(snapshot: Snapshot): [string, number][] {
  const totals = new Map<string, number>();
  for (const row of snapshot.rentals) {
    // Expired rentals remain booked sales. No bank payment or margin is implied.
    if (!['booked', 'active', 'purchased', 'expired'].includes(row.status)) continue;
    totals.set(row.currency, (totals.get(row.currency) ?? 0) + row.amount_minor);
    if (!Number.isSafeInteger(totals.get(row.currency))) throw new Error('Commercial total exceeds safe integer range.');
  }
  return [...totals].sort(([a], [b]) => a.localeCompare(b));
}

export function safeError(error: unknown): string {
  const text = error instanceof Error ? error.message : 'The service request failed.';
  return text.replace(/Bearer\s+\S+/gi, 'Bearer [redacted]')
    .replace(/eyJ[\w-]+\.[\w-]+\.[\w-]+/g, '[redacted token]')
    .replace(/(password|token|secret|sig)=([^;&\s]+)/gi, '$1=[redacted]').slice(0, 700);
}

export function dateLabel(value: Date | string | undefined): string {
  if (!value) return 'Not started';
  const date = new Date(value);
  return Number.isFinite(date.getTime())
    ? new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).format(date) + ' UTC'
    : 'Invalid timestamp';
}

export function safeUrl(url: string): string | undefined {
  try { return new URL(url).protocol === 'https:' ? url : undefined; }
  catch { return undefined; }
}
