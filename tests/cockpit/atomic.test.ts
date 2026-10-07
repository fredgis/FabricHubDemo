import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { OperatorGrant } from '../../apps/cockpit/rayfin/data/schema';
const driver = vi.hoisted(() => ({ queries: [] as string[], prior: [] as unknown[], allowed: true,
  commit: vi.fn(), rollback: vi.fn(), begin: vi.fn() }));
vi.mock('../../apps/cockpit/rayfin/functions/node_modules/mssql', () => {
  class Transaction { begin = driver.begin; commit = driver.commit; rollback = driver.rollback; }
  class Request {
    input() { return this; }
    async query(query: string) {
      driver.queries.push(query);
      if (query.includes('FROM dbo.OperatorGrant')) return { recordset: driver.allowed ? [{ id: 'grant' }] : [] };
      if (query.includes('FROM dbo.CommandReceipt')) return { recordset: driver.prior };
      return { recordset: [] };
    }
  }
  return { default: { Transaction, Request, ISOLATION_LEVEL: { SERIALIZABLE: 4 },
    UniqueIdentifier: 'uuid', NVarChar: () => 'text', DateTime2: 'date' } };
});
import { atomic } from '../../apps/cockpit/rayfin/functions/src/storage';
import { canonical } from '../../apps/cockpit/rayfin/functions/src/domain';
import { createHash } from 'node:crypto';
import type sql from '../../apps/cockpit/rayfin/functions/node_modules/mssql';

const grant = { id: 'grant', user_id: 'operator' } as OperatorGrant;
const expected = { entity_key: 'order', status: 'booked', event_ids: ['event'] };
const fingerprint = createHash('sha256').update(canonical({ operation: 'placeOrder', parameters: { offer: 'one' }, user_id: 'operator' })).digest('hex');
beforeEach(() => {
  driver.queries = []; driver.prior = []; driver.allowed = true;
  driver.begin.mockClear(); driver.commit.mockClear(); driver.rollback.mockClear();
});
describe('server transaction and idempotency', () => {
  it('commits the business callback and receipt in one serializable transaction', async () => {
    const work = vi.fn(async () => expected);
    expect(await atomic({} as sql.ConnectionPool, grant, 'key-1', 'placeOrder', { offer: 'one' }, work)).toEqual(expected);
    expect(driver.begin).toHaveBeenCalledWith(4); expect(work).toHaveBeenCalledOnce();
    expect(driver.queries.some(q => q.includes('INSERT dbo.CommandReceipt'))).toBe(true);
    expect(driver.commit).toHaveBeenCalledOnce(); expect(driver.rollback).not.toHaveBeenCalled();
  });
  it('replays the exact receipt without creating a second sale or event', async () => {
    driver.prior = [{ fingerprint, result_json: JSON.stringify(expected) }];
    const work = vi.fn();
    expect(await atomic({} as sql.ConnectionPool, grant, 'key-1', 'placeOrder', { offer: 'one' }, work)).toEqual(expected);
    expect(work).not.toHaveBeenCalled(); expect(driver.queries.some(q => q.includes('INSERT'))).toBe(false);
  });
  it('rejects reuse of a key with different parameters', async () => {
    driver.prior = [{ fingerprint: 'another', result_json: JSON.stringify(expected) }];
    const work = vi.fn();
    await expect(atomic({} as sql.ConnectionPool, grant, 'key-1', 'placeOrder', { offer: 'two' }, work)).rejects.toThrow('different command');
    expect(work).not.toHaveBeenCalled(); expect(driver.rollback).toHaveBeenCalledOnce();
  });
  it('rolls back business failure and never writes a success receipt', async () => {
    await expect(atomic({} as sql.ConnectionPool, grant, 'key-1', 'placeOrder', {}, async () => {
      throw new Error('Outbox write failed');
    })).rejects.toThrow('Outbox write failed');
    expect(driver.commit).not.toHaveBeenCalled(); expect(driver.rollback).toHaveBeenCalledOnce();
    expect(driver.queries.some(q => q.includes('INSERT dbo.CommandReceipt'))).toBe(false);
  });
  it('rechecks revoked operator grants inside the SQL transaction', async () => {
    driver.allowed = false;
    const work = vi.fn();
    await expect(atomic({} as sql.ConnectionPool, grant, 'key-1', 'placeOrder', {}, work)).rejects.toThrow('revoked');
    expect(work).not.toHaveBeenCalled();
  });
});
