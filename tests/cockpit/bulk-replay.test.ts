// Isolated database-boundary test double. It is never used by production tools.
// Observable contract: a committed chunk is replayable after a lost response.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { OperatorGrant } from '../../apps/cockpit/rayfin/data/schema';
const db = vi.hoisted(() => ({
  receipts: new Map<string, { fingerprint: string; result_json: string }>(),
  orders: 0, events: 0, sequence: 0, authorized: true, failOutbox: false,
}));
vi.mock('../../apps/cockpit/rayfin/functions/node_modules/mssql', () => {
  class Transaction {
    state!: { receipts: typeof db.receipts; orders: number; events: number; sequence: number };
    async begin() { this.state = { receipts: new Map(db.receipts), orders: db.orders, events: db.events, sequence: db.sequence }; }
    async commit() { Object.assign(db, this.state); }
    async rollback() { /* Discard the uncommitted snapshot. */ }
  }
  class Request {
    tx: Transaction;
    params: Record<string, unknown> = {};
    constructor(tx: Transaction) { this.tx = tx; }
    input(name: string, _type: unknown, value: unknown) { this.params[name] = value; return this; }
    async query(query: string) {
      const state = this.tx.state;
      if (query.includes('FROM dbo.OperatorGrants')) return { recordset: db.authorized ? [{ id: 'grant' }] : [] };
      if (query.includes('SELECT fingerprint,result_json')) {
        const receipt = state.receipts.get(String(this.params.key)); return { recordset: receipt ? [receipt] : [] };
      }
      if (query.includes('SELECT * FROM dbo.VolumeRuns')) return { recordset: [{
        run_key: 'small', user_id: 'operator', fingerprint: this.params.fingerprint,
        status: 'running', cancel_requested: false, lease_id: 'lease',
        lease_expires_at: new Date(Date.now() + 60000),
      }] };
      if (query.includes('SELECT COUNT(*) AS pending')) return { recordset: [{ pending: state.events }] };
      if (query.includes('/* bulk-source-transactions */')) {
        const rows = JSON.parse(String(this.params.input)) as { order_id: string; source_transaction_key: string }[];
        state.orders += rows.length;
        return { recordset: rows.flatMap(row => [
          { phase: 0, source_transaction_key: row.source_transaction_key, event_type: 'rental.created',
            entity_key: row.order_id, payload_json: JSON.stringify({ order_id: row.order_id, status: 'booked' }) },
          { phase: 1, source_transaction_key: row.source_transaction_key, event_type: 'rental.updated',
            entity_key: row.order_id, payload_json: JSON.stringify({ order_id: row.order_id, status: 'active' }) },
          { phase: 2, source_transaction_key: row.source_transaction_key, event_type: 'playback.created',
            entity_key: `play-${row.order_id}`, payload_json: JSON.stringify({ session_id: `play-${row.order_id}`, status: 'playing' }) },
          ...Array.from({ length: Number(this.params.progress) }, (_, i) => ({
            phase: 3 + i, source_transaction_key: row.source_transaction_key, event_type: 'playback.updated',
            entity_key: `play-${row.order_id}`, payload_json: JSON.stringify({ session_id: `play-${row.order_id}`, position_seconds: i + 1 }),
          })),
        ]) };
      }
      if (query.includes('SET value=value+@count')) {
        state.sequence += Number(this.params.count); return { recordset: [{ value: state.sequence }] };
      }
      if (query.includes('INSERT dbo.Outboxes')) {
        if (db.failOutbox) throw new Error('Outbox persistence rejected');
        state.events += JSON.parse(String(this.params.events)).length;
      }
      if (query.includes('INSERT dbo.CommandReceipts')) {
        state.receipts.set(String(this.params.key), { fingerprint: String(this.params.fingerprint), result_json: String(this.params.result) });
      }
      return { recordset: [], rowsAffected: [1] };
    }
  }
  return { default: { Transaction, Request, ISOLATION_LEVEL: { SERIALIZABLE: 4 },
    UniqueIdentifier: 'uuid', NVarChar: () => 'text', DateTime2: 'date', Int: 'int', MAX: -1 } };
});
import { bulkSourceTransactions } from '../../apps/cockpit/rayfin/functions/src/volume-batch';
import type sql from '../../apps/cockpit/rayfin/functions/node_modules/mssql';
const profile = { run_key: 'small', total_orders: 2, batch_size: 2, progress_updates: 7, purchase_every: 0 };
const rows = [
  { source_transaction_key: 'small/0', customer_key: 'MSF-C0001', offer_key: 'MSF-FILM-SINTEL:FR:RENTAL' },
  { source_transaction_key: 'small/1', customer_key: 'MSF-C0002', offer_key: 'MSF-FILM-SPRING:BE:RENTAL' },
];
const grant = { id: 'grant', user_id: 'operator' } as OperatorGrant;
const binding = { profile, source_manifest_hash: 'a'.repeat(64), policy_hash: 'b'.repeat(64), lease_id: 'lease' };
beforeEach(() => { db.receipts.clear(); db.orders = 0; db.events = 0; db.sequence = 0; db.authorized = true; db.failOutbox = false; });
describe('bulk committed source transactions', () => {
  it('replays a committed chunk without another order or outbox event', async () => {
    const first = await bulkSourceTransactions({} as sql.ConnectionPool, grant, binding, 0, rows);
    const replay = await bulkSourceTransactions({} as sql.ConnectionPool, grant, binding, 0, rows);
    expect(replay).toEqual(first);
    expect({ orders: db.orders, events: db.events, receipts: db.receipts.size }).toEqual({ orders: 2, events: 20, receipts: 1 });
  });
  it('rejects changed parameters under the same batch key without duplicate effects', async () => {
    await bulkSourceTransactions({} as sql.ConnectionPool, grant, binding, 0, rows);
    await expect(bulkSourceTransactions({} as sql.ConnectionPool, grant, binding, 0,
      [rows[0], { ...rows[1], offer_key: 'another-offer' }])).rejects.toThrow('different command');
    expect({ orders: db.orders, events: db.events }).toEqual({ orders: 2, events: 20 });
  });
  it('rolls back all source transactions when outbox persistence fails and permits safe retry', async () => {
    db.failOutbox = true;
    await expect(bulkSourceTransactions({} as sql.ConnectionPool, grant, binding, 0, rows)).rejects.toThrow('Outbox persistence rejected');
    expect({ orders: db.orders, events: db.events, receipts: db.receipts.size }).toEqual({ orders: 0, events: 0, receipts: 0 });
    db.failOutbox = false;
    await bulkSourceTransactions({} as sql.ConnectionPool, grant, binding, 0, rows);
    expect({ orders: db.orders, events: db.events }).toEqual({ orders: 2, events: 20 });
  });
  it('rechecks a revoked operator grant even for committed replay', async () => {
    await bulkSourceTransactions({} as sql.ConnectionPool, grant, binding, 0, rows);
    db.authorized = false;
    await expect(bulkSourceTransactions({} as sql.ConnectionPool, grant, binding, 0, rows)).rejects.toThrow('revoked');
    expect({ orders: db.orders, events: db.events }).toEqual({ orders: 2, events: 20 });
  });
});
