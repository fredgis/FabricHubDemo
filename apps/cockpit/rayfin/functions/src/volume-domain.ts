import { createHash } from 'node:crypto';
import type { CommandResult } from './domain.js';
import { canonical, key } from './domain.js';

export type VolumeProfile = { run_key: string; total_orders: number; batch_size: number;
  progress_updates: number; purchase_every: number };
export type SourceTransaction = { source_transaction_key: string; customer_key: string; offer_key: string };
export type BatchResult = CommandResult & { orders: number; events: number; batch_index: number };

function integer(value: unknown, label: string, min: number, max: number): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < min || value > max)
    throw new Error(`${label} must be an integer ${min}-${max}.`);
  return value;
}
export function validateProfile(value: unknown): VolumeProfile {
  const p = value as Partial<VolumeProfile>;
  if (!p || typeof p !== 'object' || typeof p.run_key !== 'string' ||
      !/^[a-zA-Z0-9_-]{1,64}$/.test(p.run_key)) throw new Error('run_key must be 1-64 safe characters.');
  return {
    run_key: p.run_key,
    total_orders: integer(p.total_orders, 'total_orders', 1, 100000),
    batch_size: integer(p.batch_size, 'batch_size', 1, 100),
    progress_updates: integer(p.progress_updates, 'progress_updates', 1, 16),
    purchase_every: integer(p.purchase_every, 'purchase_every', 0, 1000),
  };
}
export function volumeEstimate(p: VolumeProfile): { orders: number; events: number; batches: number } {
  return { orders: p.total_orders, events: p.total_orders * (3 + p.progress_updates),
    batches: Math.ceil(p.total_orders / p.batch_size) };
}
export function batchKey(runKey: string, index: number): string {
  key(runKey, 'run key');
  integer(index, 'batch index', 0, 99999);
  return key(`volume:${runKey}:batch:${index}`, 'batch key');
}
export function digest(value: unknown): string {
  return createHash('sha256').update(canonical(value)).digest('hex');
}
export function stableUuid(namespace: string): string {
  const hex = createHash('sha256').update(namespace).digest('hex').slice(0, 32).split('');
  hex[12] = '5'; hex[16] = '8';
  const h = hex.join('');
  return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;
}

export function validateBatch(p: VolumeProfile, index: number, value: unknown): SourceTransaction[] {
  if (!Number.isInteger(index) || index < 0 || index >= volumeEstimate(p).batches)
    throw new Error('Batch index is outside the run.');
  const expected = Math.min(p.batch_size, p.total_orders - index * p.batch_size);
  if (!Array.isArray(value) || value.length !== expected) throw new Error(`Expected ${expected} source transactions.`);
  const seen = new Set<string>();
  return value.map(row => {
    if (!row || typeof row !== 'object' ||
      Object.keys(row).some(name => !['source_transaction_key', 'customer_key', 'offer_key'].includes(name)))
      throw new Error('Prices, expiry and progress policy are server-owned; unexpected transaction fields.');
    const parsed = { source_transaction_key: key(row.source_transaction_key, 'source transaction key'),
      customer_key: key(row.customer_key, 'customer key'), offer_key: key(row.offer_key, 'offer key') };
    if (seen.has(parsed.source_transaction_key)) throw new Error('Duplicate source transaction key in batch.');
    seen.add(parsed.source_transaction_key);
    return parsed;
  });
}
