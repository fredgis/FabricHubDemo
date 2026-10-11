// @vitest-environment node
import { readFileSync } from 'node:fs';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AppSchema } from '../../apps/cockpit/rayfin/data/schema';
import { operationalBinding as binding } from './operational-fixture';

type Row = Record<string, unknown>;
type Transaction = { rentals: Row[]; playback: Row[] };
const calls = vi.hoisted(() => ({
  leases: 0, releases: 0, pool: {}, snapshot: 1 as number | undefined,
  queries: [] as { query: string; parent: unknown; values: Record<string, unknown>; types: Record<string, unknown> }[],
  begins: [] as { tx: unknown; isolation: number }[], commits: [] as unknown[], rollbacks: [] as unknown[],
  rentals: [] as Row[], playback: [] as Row[], totalOverride: undefined as unknown,
  beginError: null as Error | null, queryError: null as Error | null, commitError: null as Error | null,
  rollbackError: null as Error | null, afterCounts: undefined as (() => void) | undefined,
}));
vi.mock('../../apps/cockpit/rayfin/functions/src/operational-connection', () => ({
  withOperationalPool: async (_binding: unknown, _token: string, read: (pool: unknown) => Promise<unknown>) => {
    calls.leases++;
    try { return await read(calls.pool); }
    finally { calls.releases++; }
  },
}));
vi.mock('../../apps/cockpit/rayfin/functions/node_modules/mssql', () => {
  class Request {
    values: Record<string, unknown> = {};
    types: Record<string, unknown> = {};
    constructor(readonly parent: unknown) {}
    input(name: string, type: unknown, value: unknown) {
      this.values[name] = value; this.types[name] = type; return this;
    }
    async query(query: string) {
      calls.queries.push({ query, parent: this.parent, values: this.values, types: this.types });
      if (query.includes('sys.databases')) {
        return { recordset: calls.snapshot === undefined ? [] : [{ snapshot_isolation_state: calls.snapshot }] };
      }
      if (calls.queryError) throw calls.queryError;
      const tx = this.parent as Transaction;
      if (query.includes('COUNT_BIG')) {
        const counts = { orders: calls.totalOverride ?? String(tx.rentals.length), sessions: String(tx.playback.length) };
        calls.afterCounts?.();
        return { recordset: [counts] };
      }
      const ordersOffset = Number(this.values.ordersOffset);
      const playbackOffset = Number(this.values.playbackOffset);
      const limit = Number(this.values.pageSize);
      return { recordsets: [
        tx.rentals.slice(ordersOffset, ordersOffset + limit), tx.playback.slice(playbackOffset, playbackOffset + limit),
      ] };
    }
  }
  class MockTransaction {
    rentals: Row[] = [];
    playback: Row[] = [];
    async begin(isolation: number) {
      calls.begins.push({ tx: this, isolation });
      if (calls.beginError) throw calls.beginError;
      this.rentals = [...calls.rentals].sort((a, b) =>
        Number(b.created_at) - Number(a.created_at) || String(b.order_id).localeCompare(String(a.order_id)));
      this.playback = [...calls.playback].sort((a, b) => String(a.session_id).localeCompare(String(b.session_id)));
    }
    async commit() { calls.commits.push(this); if (calls.commitError) throw calls.commitError; }
    async rollback() { calls.rollbacks.push(this); if (calls.rollbackError) throw calls.rollbackError; }
  }
  return { default: { Request, Transaction: MockTransaction, BigInt: 'bigint', Int: 'int',
    ISOLATION_LEVEL: { SNAPSHOT: 5, SERIALIZABLE: 4 } } };
});
import sql from '../../apps/cockpit/rayfin/functions/node_modules/mssql';
import { readOperationalOrders } from '../../apps/cockpit/rayfin/functions/src/operational-orders';

function rental(index: number): Row {
  return { id: `rental-${index}`, order_id: `order-${String(index).padStart(4, '0')}`, customer_key: 'customer',
    offer_key: 'offer', status: 'booked', amount_minor: 399, currency: 'EUR',
    created_at: new Date('2026-10-11T08:00:00Z'), start_deadline: null, first_play_at: null, expires_at: null };
}
function playback(index: number): Row {
  return { id: `playback-${index}`, session_id: `session-${String(index).padStart(4, '0')}`,
    order_id: `order-${index}`, content_key: 'content', customer_key: 'customer', position_seconds: 10, status: 'playing' };
}
beforeEach(() => {
  Object.assign(calls, { leases: 0, releases: 0, snapshot: 1, queries: [], begins: [], commits: [], rollbacks: [],
    rentals: Array.from({ length: 137 }, (_, i) => rental(i + 1)),
    playback: Array.from({ length: 119 }, (_, i) => playback(i + 1)), totalOverride: undefined,
    beginError: null, queryError: null, commitError: null, rollbackError: null, afterCounts: undefined,
    pool: { request: () => new sql.Request(calls.pool as sql.ConnectionPool) } });
});

describe('bounded operational orders SQL reads', () => {
  it('uses fixed SQL-bound pages, whole-table aggregates and stable unique ordering', async () => {
    const page = await readOperationalOrders(binding, 'token', 2, 3);
    expect(page.orders).toEqual({ page: 2, pageSize: 50, total: 137 });
    expect(page.sessions).toEqual({ page: 3, pageSize: 50, total: 119 });
    expect(page.rentals).toHaveLength(50); expect(page.playback).toHaveLength(19);
    expect(page.rentals[0].order_id).toBe('order-0087'); expect(page.rentals[49].order_id).toBe('order-0038');
    expect(page.playback[0].session_id).toBe('session-0101');
    const counts = calls.queries.find(call => call.query.includes('COUNT_BIG'))!;
    expect(counts.query).toContain('(SELECT COUNT_BIG(*) FROM dbo.Rentals)');
    expect(counts.query).toContain('(SELECT COUNT_BIG(*) FROM dbo.Playbacks)');
    expect(counts.query).not.toMatch(/OFFSET|FETCH|TOP|WHERE/i);
    const rows = calls.queries.find(call => call.query.includes('OFFSET'))!;
    expect(rows.query).toContain('FROM dbo.Rentals ORDER BY created_at DESC,order_id DESC');
    expect(rows.query).toContain('FROM dbo.Playbacks ORDER BY session_id ASC');
    expect(rows.query).toContain('OFFSET @ordersOffset ROWS FETCH NEXT @pageSize ROWS ONLY');
    expect(rows.query).toContain('OFFSET @playbackOffset ROWS FETCH NEXT @pageSize ROWS ONLY');
    expect(rows.values).toEqual({ ordersOffset: 50, playbackOffset: 100, pageSize: 50 });
    expect(rows.types).toEqual({ ordersOffset: 'bigint', playbackOffset: 'bigint', pageSize: 'int' });
    expect(calls.queries).toHaveLength(3);
    expect(calls.leases).toBe(1); expect(calls.releases).toBe(1);
  });

  it('reads both counts and pages on one short snapshot transaction', async () => {
    calls.afterCounts = () => { calls.rentals = []; calls.playback = []; };
    const page = await readOperationalOrders(binding, 'token', 1, 1);
    const tx = calls.begins[0].tx;
    expect(calls.begins).toEqual([{ tx, isolation: 5 }]);
    expect(calls.queries[0].parent).toBe(calls.pool);
    expect(calls.queries.slice(1).every(call => call.parent === tx)).toBe(true);
    expect(calls.commits).toEqual([tx]); expect(calls.rollbacks).toEqual([]);
    expect(page.orders.total).toBe(137); expect(page.rentals).toHaveLength(50);
    expect(page.sessions.total).toBe(119); expect(page.playback).toHaveLength(50);
  });

  it.each([0, 2, 3, undefined])('uses serializable when snapshot is not ON (state=%s), without DDL', async snapshot => {
    calls.snapshot = snapshot;
    await readOperationalOrders(binding, 'token', 1, 1);
    expect(calls.begins[0].isolation).toBe(4);
    expect(calls.queries.every(call => !/\b(ALTER|CREATE|DROP|INSERT|UPDATE|DELETE|MERGE)\b/i.test(call.query))).toBe(true);
  });

  it('clamps both pages after shrinkage and keeps empty datasets on page one', async () => {
    const before = await readOperationalOrders(binding, 'token', Number.MAX_SAFE_INTEGER, Number.MAX_SAFE_INTEGER);
    expect(before.orders).toEqual({ page: 3, pageSize: 50, total: 137 });
    expect(before.sessions).toEqual({ page: 3, pageSize: 50, total: 119 });
    expect(before.rentals).toHaveLength(37); expect(before.playback).toHaveLength(19);
    calls.rentals = [rental(1)]; calls.playback = [];
    const after = await readOperationalOrders(binding, 'token', 3, 3);
    expect(after.orders).toEqual({ page: 1, pageSize: 50, total: 1 });
    expect(after.sessions).toEqual({ page: 1, pageSize: 50, total: 0 });
    expect(after.rentals).toHaveLength(1); expect(after.playback).toEqual([]);
    expect(calls.queries.at(-1)?.values).toEqual({ ordersOffset: 0, playbackOffset: 0, pageSize: 50 });
    calls.rentals = [];
    const empty = await readOperationalOrders(binding, 'token', 20, 40);
    expect(empty.rentals).toEqual([]); expect(empty.playback).toEqual([]);
    expect(empty.orders).toEqual({ page: 1, pageSize: 50, total: 0 });
  });

  it('uses the unique order key to break equal timestamps without page overlaps', async () => {
    const first = await readOperationalOrders(binding, 'token', 1, 1);
    const second = await readOperationalOrders(binding, 'token', 2, 2);
    const combined = [...first.rentals, ...second.rentals];
    expect(new Set(combined.map(row => row.order_id)).size).toBe(100);
    expect(combined[0].order_id).toBe('order-0137');
    expect(combined.at(-1)?.order_id).toBe('order-0038');
  });

  it.each([0, -1, 1.5, NaN, Infinity, -Infinity, Number.MAX_SAFE_INTEGER + 1, '1', null, undefined])(
    'rejects invalid inputs before leasing SQL: %s', async value => {
      await expect(readOperationalOrders(binding, 'token', value as number, 1)).rejects.toThrow('ordersPage');
      await expect(readOperationalOrders(binding, 'token', 1, value as number)).rejects.toThrow('playbackPage');
      expect(calls.leases).toBe(0); expect(calls.queries).toEqual([]);
    });

  it('keeps large COUNT_BIG totals and offsets exact instead of narrowing them to SQL int', async () => {
    calls.totalOverride = '5000000001';
    const result = await readOperationalOrders(binding, 'token', Number.MAX_SAFE_INTEGER, 1);
    expect(result.orders).toEqual({ page: 100000001, pageSize: 50, total: 5000000001 });
    expect(calls.queries.at(-1)?.values.ordersOffset).toBe(5000000000);
    expect(calls.queries.at(-1)?.types.ordersOffset).toBe('bigint');
  });

  it.each(['9007199254740992', '-1', '1.5', '', 'not-a-count', {}, -1, 1.5, Infinity])(
    'rejects inexact or malformed counts without returning partial KPIs: %s', async value => {
      calls.totalOverride = value;
      await expect(readOperationalOrders(binding, 'token', 1, 1)).rejects.toThrow('supported range');
      expect(calls.queries.some(call => call.query.includes('OFFSET'))).toBe(false);
      expect(calls.commits).toEqual([]); expect(calls.rollbacks).toHaveLength(1); expect(calls.releases).toBe(1);
    });

  it('selects only the existing business fields and normalizes nullable dates to the entity contract', async () => {
    calls.rentals = [rental(1)]; calls.playback = [playback(1)];
    const result = await readOperationalOrders(binding, 'token', 1, 1);
    const rows = calls.queries.at(-1)!.query;
    const selections = [...rows.matchAll(/SELECT\s+([\s\S]*?)\s+FROM dbo\.(Rentals|Playbacks)/g)];
    expect(selections[0][1].replace(/\s/g, '').split(',')).toEqual([
      'id', 'order_id', 'customer_key', 'offer_key', 'status', 'amount_minor', 'currency',
      'created_at', 'start_deadline', 'first_play_at', 'expires_at',
    ]);
    expect(selections[1][1].replace(/\s/g, '').split(',')).toEqual([
      'id', 'session_id', 'order_id', 'content_key', 'customer_key', 'position_seconds', 'status',
    ]);
    const row: AppSchema['Rental'] = result.rentals[0];
    expect(row.created_at).toBeInstanceOf(Date);
    expect(row.start_deadline).toBeUndefined(); expect(row.first_play_at).toBeUndefined(); expect(row.expires_at).toBeUndefined();
    expect(rows).not.toMatch(/\b(Outboxes|CommandReceipts|OperatorGrants|Customers)\b|SELECT\s+\*/i);
  });

  it.each(['beginError', 'queryError', 'commitError'] as const)('rolls back and releases on %s without replay', async kind => {
    calls[kind] = new Error(`${kind} failed`);
    await expect(readOperationalOrders(binding, 'token', 1, 1)).rejects.toThrow(`${kind} failed`);
    expect(calls.begins).toHaveLength(1); expect(calls.rollbacks).toHaveLength(1);
    expect(calls.leases).toBe(1); expect(calls.releases).toBe(1);
  });

  it('preserves a query failure when XACT_ABORT already rolled back the transaction', async () => {
    calls.queryError = new Error('read failed'); calls.rollbackError = new Error('already rolled back');
    await expect(readOperationalOrders(binding, 'token', 1, 1)).rejects.toThrow('read failed');
    expect(calls.releases).toBe(1); expect(calls.commits).toEqual([]);
  });

  it('locks the current unfiltered authenticated-reader policy before using app-identity SQL', () => {
    const schema = readFileSync(new URL('../../apps/cockpit/rayfin/data/schema.ts', import.meta.url), 'utf8');
    for (const entity of ['Rental', 'Playback']) {
      expect(schema, `${entity} permission changes require revisiting the SQL paging authorization`)
        .toMatch(new RegExp(`@entity\\(\\)\\s*@authenticated\\('read'\\)\\s*export class ${entity} \\{`));
    }
  });
});
