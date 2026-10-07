import { describe, expect, it } from 'vitest';
import { assertOperator, canPlay, canonical, controlLimit, deadline, isExpired, key, offerPolicy } from '../../apps/cockpit/rayfin/functions/src/domain';
import type { Offer, Rental } from '../../apps/cockpit/rayfin/data/schema';
import { allPages, money, revenueByCurrency, safeError, safeUrl, type Snapshot } from '../../apps/cockpit/src/services/business';

const now = new Date('2026-10-07T12:00:00.000Z');
const offer = { transaction_type: 'TVOD', price_minor: 499, currency: 'EUR',
  start_window_hours: 72, play_window_hours: 24 } as Offer;
const order = { status: 'booked', start_deadline: new Date('2026-10-07T12:00:00.000Z') } as Rental;

describe('commercial policy', () => {
  it('uses exact minor units and explicit offer windows', () => {
    expect(deadline(offer, now)).toBe('2026-10-10T12:00:00.000Z');
    expect(money(499, 'EUR')).toContain('4.99');
    expect(money(500, 'JPY')).toContain('500');
    expect(money(Number.MAX_SAFE_INTEGER, 'EUR')).toContain('.91');
    expect(money(-1, 'EUR')).toContain('-€0.01');
  });
  it('rejects fractional and unsafe amounts', () => {
    expect(() => offerPolicy({ ...offer, price_minor: 4.99 })).toThrow('minor-unit');
    expect(() => offerPolicy({ ...offer, price_minor: Number.MAX_SAFE_INTEGER })).toThrow();
  });
  it('rejects absent/zero rental policies and SVOD commerce', () => {
    expect(() => offerPolicy({ ...offer, play_window_hours: 0 })).toThrow('windows');
    expect(() => offerPolicy({ ...offer, transaction_type: 'SVOD' })).toThrow('TVOD and EST');
  });
  it('allows playback immediately before first-start boundary', () => {
    expect(() => canPlay(order, offer, new Date(now.getTime() - 1))).not.toThrow();
  });
  it('rejects playback exactly at and after first-start boundary', () => {
    expect(() => canPlay(order, offer, now)).toThrow('expired');
    expect(() => canPlay(order, offer, new Date(now.getTime() + 1))).toThrow('expired');
    expect(isExpired(order, now)).toBe(true);
  });
  it('uses the first-play window rather than start deadline after activation', () => {
    const active = { ...order, status: 'active', first_play_at: new Date('2026-10-06T12:00:00Z'),
      start_deadline: new Date('2026-10-10T12:00:00Z'), expires_at: now };
    expect(() => canPlay(active, offer, now)).toThrow('expired');
    expect(isExpired(active, now)).toBe(true);
  });
  it('does not expire purchases', () => {
    const purchase = { ...order, status: 'purchased', start_deadline: undefined };
    expect(() => canPlay(purchase, { ...offer, transaction_type: 'EST' }, now)).not.toThrow();
    expect(isExpired(purchase, now)).toBe(false);
  });
  it('rejects malformed deadlines', () => {
    expect(() => canPlay({ ...order, start_deadline: new Date('invalid') }, offer, now)).toThrow('expired');
  });
  it('counts expired rentals as recorded sales and keeps currencies separate', () => {
    const data = { rentals: [
      { status: 'expired', amount_minor: 499, currency: 'EUR' },
      { status: 'purchased', amount_minor: 1299, currency: 'EUR' },
      { status: 'booked', amount_minor: 300, currency: 'USD' },
    ] } as Snapshot;
    expect(revenueByCurrency(data)).toEqual([['EUR', 1798], ['USD', 300]]);
  });
});

describe('permissions and bounded controls', () => {
  it('denies viewers, revoked grants and grants at the expiration boundary', () => {
    expect(() => assertOperator(undefined, now)).toThrow('Operator permission');
    expect(() => assertOperator({ enabled: false, expires_at: new Date(now.getTime() + 1) }, now)).toThrow();
    expect(() => assertOperator({ enabled: true, expires_at: now }, now)).toThrow();
  });
  it('accepts only an enabled unexpired grant', () => {
    expect(() => assertOperator({ enabled: true, expires_at: new Date(now.getTime() + 1) }, now)).not.toThrow();
    expect(() => assertOperator({ enabled: true, expires_at: 'invalid' }, now)).toThrow();
  });
  it('rejects privileged statuses and unbounded control types/counts', () => {
    expect(() => controlLimit('simulate', 100)).not.toThrow();
    for (const count of [0, 101, 1.5, NaN]) expect(() => controlLimit('start', count)).toThrow();
    expect(() => controlLimit('completed', 1)).toThrow('Unsupported');
    expect(() => key("'; DROP TABLE Rental", 'key')).toThrow('Invalid');
  });
});

describe('canonical envelopes and data boundaries', () => {
  it('produces stable JSON independent of object property order', () => {
    expect(canonical({ b: { z: 1, a: 'x' }, a: 3 })).toBe(canonical({ a: 3, b: { a: 'x', z: 1 } }));
    expect(JSON.parse(canonical({ status: 'booked', amount_minor: 499 }))).toEqual({ amount_minor: 499, status: 'booked' });
    expect(canonical({ a: 3, _a: 1, A: 2 })).toBe('{"A":2,"_a":1,"a":3}');
  });
  it('retains UTC checkpoint timestamps instead of replacing Date objects with empty records', () => {
    expect(canonical({ updated_at: new Date('2026-10-07T13:00:00Z') }))
      .toBe('{"updated_at":"2026-10-07T13:00:00.000Z"}');
  });
  it('reads every data page rather than silently calculating one-page KPIs', async () => {
    const cursors: (string | undefined)[] = [];
    const result = await allPages(async cursor => {
      cursors.push(cursor);
      return cursor ? { items: [3], hasNextPage: false } : { items: [1, 2], hasNextPage: true, endCursor: 'next' };
    });
    expect(result).toEqual([1, 2, 3]); expect(cursors).toEqual([undefined, 'next']);
  });
  it('preserves connection failures and rejects stalled paging', async () => {
    await expect(allPages(async () => { throw new Error('Actual service offline'); })).rejects.toThrow('Actual service offline');
    await expect(allPages(async () => ({ items: [], hasNextPage: true, endCursor: null }))).rejects.toThrow('did not advance');
  });
  it('does not allow active links or credential-bearing error output', () => {
    expect(safeUrl('javascript:alert(1)')).toBeUndefined();
    expect(safeUrl('https://studio.blender.org/')).toBe('https://studio.blender.org/');
    expect(safeError(new Error('Bearer secret-token password=abcdef'))).not.toContain('abcdef');
    expect(safeError(new Error('Bearer secret-token'))).not.toContain('secret-token');
  });
});
