import { describe, expect, it } from 'vitest';
import { batchKey, validateProfile, volumeEstimate, validateBatch } from '../../apps/cockpit/rayfin/functions/src/volume-domain';

describe('bounded persisted-volume contract', () => {
  it('plans 50,000 orders and 500,000 real state-change events in 500 replayable chunks', () => {
    const profile = validateProfile({ run_key: 'msflix-volume-01', total_orders: 50000,
      batch_size: 100, progress_updates: 7, purchase_every: 5 });
    expect(volumeEstimate(profile)).toEqual({ orders: 50000, events: 500000, batches: 500 });
    expect(batchKey(profile.run_key, 0)).toBe('volume:msflix-volume-01:batch:0');
  });
  it('rejects changed batch boundaries, duplicate natural transaction keys and client policy fields', () => {
    const profile = validateProfile({ run_key: 'small', total_orders: 2, batch_size: 2, progress_updates: 7, purchase_every: 0 });
    const row = { source_transaction_key: 'source-1', customer_key: 'MSF-C0001', offer_key: 'MSF-FILM-SINTEL:FR:RENTAL' };
    expect(() => validateBatch(profile, 0, [row])).toThrow('Expected 2');
    expect(() => validateBatch(profile, 0, [row, row])).toThrow('Duplicate');
    expect(() => validateBatch(profile, 1, [row])).toThrow('outside');
    expect(() => validateBatch(profile, 0, [row, { ...row, source_transaction_key: 'source-2', price_minor: 1 }])).toThrow('server-owned');
  });
});
