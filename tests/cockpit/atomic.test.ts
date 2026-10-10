import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { OperatorGrant } from '../../apps/cockpit/rayfin/data/schema';
const driver = vi.hoisted(() => ({ queries: [] as string[], prior: [] as unknown[], pending: [] as unknown[], allowed: true,
  writes: [] as { query: string; values: Record<string, unknown> }[],
  commit: vi.fn(), rollback: vi.fn(), begin: vi.fn() }));
vi.mock('../../apps/cockpit/rayfin/functions/node_modules/mssql', () => {
  class Transaction { begin = driver.begin; commit = driver.commit; rollback = driver.rollback; }
  class Request {
    values: Record<string, unknown> = {};
    input(name: string, _type: unknown, value: unknown) { this.values[name] = value; return this; }
    async query(query: string) {
      driver.queries.push(query);
      driver.writes.push({ query, values: this.values });
      if (query.includes('FROM dbo.OperatorGrant')) return { recordset: driver.allowed ? [{ id: 'grant' }] : [] };
      if (query.includes('FROM dbo.CommandReceipt')) return { recordset: driver.prior };
      if (query.includes('FROM dbo.ControlCommands')) return { recordset: driver.pending };
      return { recordset: [] };
    }
  }
  return { default: { Transaction, Request, ISOLATION_LEVEL: { SERIALIZABLE: 4 },
    UniqueIdentifier: 'uuid', NVarChar: () => 'text', DateTime2: 'date' } };
});
import { atomic } from '../../apps/cockpit/rayfin/functions/src/storage';
import { canonical, type ControlInput } from '../../apps/cockpit/rayfin/functions/src/domain';
import { requestControl } from '../../apps/cockpit/rayfin/functions/src/commands';
import { createHash } from 'node:crypto';
import type sql from '../../apps/cockpit/rayfin/functions/node_modules/mssql';

const grant = { id: 'grant', user_id: 'operator' } as OperatorGrant;
const expected = { entity_key: 'order', status: 'booked', event_ids: ['event'] };
const fingerprint = createHash('sha256').update(canonical({ operation: 'placeOrder', parameters: { offer: 'one' }, user_id: 'operator' })).digest('hex');
beforeEach(() => {
  driver.queries = []; driver.prior = []; driver.pending = []; driver.writes = []; driver.allowed = true;
  driver.begin.mockClear(); driver.commit.mockClear(); driver.rollback.mockClear();
});
describe('source reload enqueue', () => {
  it.each(['reload_oracle', 'reload_salesforce'] as const)('serializes and replays %s in the existing atomic transaction', async type => {
    const input: ControlInput = { type, limit: 1, idempotency_key: 'reload-key' };
    const result = await atomic({} as sql.ConnectionPool, grant, input.idempotency_key, 'requestControl', input,
      store => requestControl(store, input), { runId: 'source-run' });
    expect(result).toEqual({ entity_key: expect.any(String), event_ids: [], status: 'requested' });
    expect(driver.begin).toHaveBeenCalledWith(4);
    const pending = driver.queries.find(query => query.includes('FROM dbo.ControlCommands'));
    expect(pending).toContain('WITH (UPDLOCK,HOLDLOCK)');
    expect(pending).toContain("type IN ('reload_oracle','reload_salesforce')");
    expect(pending).toContain("status IN ('requested','running','blocked')");
    const insert = driver.writes.find(write => write.query.includes('INSERT dbo.ControlCommands'))!;
    expect(insert.values).toMatchObject({ id: result.entity_key, key: input.idempotency_key, type,
      params: JSON.stringify({ limit: 1, run_id: 'source-run' }) });
    expect(insert.query).toContain("VALUES (@id,@key,@type,'requested',@params,@now,NULL,NULL)");
    driver.prior = [{ fingerprint: createHash('sha256').update(canonical({ operation: 'requestControl',
      parameters: input, user_id: grant.user_id })).digest('hex'), result_json: JSON.stringify(result) }];
    driver.queries = [];
    const work = vi.fn();
    expect(await atomic({} as sql.ConnectionPool, grant, input.idempotency_key, 'requestControl', input, work)).toEqual(result);
    expect(work).not.toHaveBeenCalled();
    expect(driver.queries.some(query => query.includes('INSERT'))).toBe(false);
    const otherSource = { ...input, type: type === 'reload_oracle' ? 'reload_salesforce' : 'reload_oracle' };
    await expect(atomic({} as sql.ConnectionPool, grant, input.idempotency_key, 'requestControl', otherSource, work))
      .rejects.toThrow('different command');
    expect(work).not.toHaveBeenCalled();
  });
  it.each(['requested', 'running', 'blocked'])('rejects a reload while another source is %s', async status => {
    driver.pending = [{ id: 'salesforce-command', type: 'reload_salesforce', status }];
    const input: ControlInput = { type: 'reload_oracle', limit: 1, idempotency_key: 'reload-key' };
    await expect(atomic({} as sql.ConnectionPool, grant, input.idempotency_key, 'requestControl', input,
      store => requestControl(store, input))).rejects.toThrow('A source reload is already requested, running or blocked');
    expect(driver.rollback).toHaveBeenCalledOnce();
    expect(driver.queries.some(query => query.includes('INSERT'))).toBe(false);
  });
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
