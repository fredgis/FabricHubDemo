// @vitest-environment node
import { EventEmitter } from 'node:events';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { deferred, operationalBinding as binding, operationalTables, operationalToken as token } from './operational-fixture';

const calls = vi.hoisted(() => ({
  connections: 0, closes: [] as number[], instances: [] as EventEmitter[], configs: [] as unknown[],
  requests: [] as { query: string; values: Record<string, unknown>; pool: number }[],
  matches: 1, tables: [] as string[], connectErrors: [] as Error[], queryError: null as Error | null,
  connectDelay: undefined as Promise<void> | undefined, closeDelay: undefined as Promise<void> | undefined,
  closeError: null as Error | null,
}));
vi.mock('../../apps/cockpit/rayfin/functions/node_modules/mssql', () => ({
  default: {
    UniqueIdentifier: 'uuid', NVarChar: () => 'text',
    ConnectionPool: class extends EventEmitter {
      index: number;
      constructor(config: unknown) {
        super(); this.index = calls.instances.length; calls.instances.push(this); calls.configs.push(config);
      }
      async connect() {
        calls.connections++;
        await calls.connectDelay;
        const error = calls.connectErrors.shift();
        if (error) throw error;
        return this;
      }
      async close() {
        calls.closes.push(this.index);
        await calls.closeDelay;
        if (calls.closeError) throw calls.closeError;
      }
      request() {
        const values: Record<string, unknown> = {};
        const request = {
          input(name: string, typeOrValue: unknown, value?: unknown) {
            values[name] = arguments.length === 2 ? typeOrValue : value;
            return request;
          },
          query: async (query: string) => {
            calls.requests.push({ query, values, pool: this.index });
            if (calls.queryError) throw calls.queryError;
            if (query.includes('FROM dbo.RuntimeBindings'))
              return { recordset: Array.from({ length: calls.matches }, () => ({ id: values.id })) };
            if (query.includes('FROM sys.tables')) return { recordset: calls.tables.map(name => ({ name })) };
            return { recordset: [] };
          },
        };
        return request;
      }
    },
  },
}));

let withPool: typeof import('../../apps/cockpit/rayfin/functions/src/operational-connection').withOperationalPool;
let dedicatedPool: typeof import('../../apps/cockpit/rayfin/functions/src/storage').poolFor;
const read = vi.fn(async () => 'fresh');
const flush = () => vi.advanceTimersByTimeAsync(0);
beforeEach(async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-11T08:00:00Z'));
  vi.resetModules();
  Object.assign(calls, { connections: 0, closes: [], instances: [], configs: [], requests: [], matches: 1,
    tables: [...operationalTables], connectErrors: [], queryError: null, connectDelay: undefined,
    closeDelay: undefined, closeError: null });
  read.mockClear();
  ({ withOperationalPool: withPool } = await import('../../apps/cockpit/rayfin/functions/src/operational-connection'));
  ({ poolFor: dedicatedPool } = await import('../../apps/cockpit/rayfin/functions/src/storage'));
});
afterEach(async () => { await vi.runOnlyPendingTimersAsync(); vi.useRealTimers(); });

describe('operational read leases', () => {
  it('reuses connections, not validation or read results', async () => {
    const credential = token();
    const first = await withPool(binding, credential, async pool => { await read(); return pool; });
    const second = await withPool(binding, credential, async pool => { await read(); return pool; });
    expect(first).toBe(second);
    expect(calls.connections).toBe(1);
    expect(read).toHaveBeenCalledTimes(2);
    expect(calls.requests.filter(call => call.query.includes('RuntimeBindings'))).toHaveLength(2);
    expect(calls.requests.filter(call => call.query.includes('sys.tables'))).toHaveLength(2);
    expect(calls.requests[0].values).toEqual({ id: binding.id, item: binding.fabric_item_id,
      workspace: binding.workspace_id, capacity: binding.capacity_id });
    expect(calls.configs[0]).toMatchObject({ server: binding.sql_server, database: binding.sql_database,
      options: { encrypt: true, trustServerCertificate: false, abortTransactionOnError: true },
      authentication: { type: 'azure-active-directory-access-token', options: { token: credential } },
      pool: { min: 0, max: 2, idleTimeoutMillis: 300_000 } });
    expect(calls.closes).toEqual([]);
  });

  it('coalesces concurrent setup but gives each lease its own requests', async () => {
    const gate = deferred(); calls.connectDelay = gate.promise;
    const credential = token();
    const pending = ['one', 'two'].map(marker => withPool(binding, credential, async pool => {
      await pool.request().input('marker', marker).query('SELECT @marker');
    }));
    await flush();
    expect(calls.connections).toBe(1); expect(calls.requests).toHaveLength(0);
    gate.resolve(); await Promise.all(pending);
    expect(calls.requests.filter(call => call.query === 'SELECT @marker').map(call => call.values))
      .toEqual([{ marker: 'one' }, { marker: 'two' }]);
    expect(calls.requests.filter(call => call.query.includes('RuntimeBindings'))).toHaveLength(2);
  });

  it('keys on the exact token, not just decoded identity', async () => {
    const credential = token();
    await withPool(binding, credential, read);
    await withPool(binding, credential.replace('.signature', '.different-signature'), read);
    expect(calls.connections).toBe(2);
  });

  it.each([
    { id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc' },
    { sql_server: 'other.database.fabric.microsoft.com' }, { sql_database: 'other-database' },
    { fabric_item_id: 'other-app' }, { workspace_id: 'other-workspace' }, { capacity_id: 'other-capacity' },
  ])('isolates every operational binding field: %j', async change => {
    const credential = token();
    await withPool(binding, credential, read);
    await withPool({ ...binding, ...change }, credential, read);
    expect(calls.connections).toBe(2);
  });

  it.each([{ verified: false }, { binding_key: 'business-gold' },
    { sql_server: 'fixture.datawarehouse.fabric.microsoft.com' }])('rejects an invalid binding before reuse: %j', async change => {
    const credential = token();
    await withPool(binding, credential, read);
    await expect(withPool({ ...binding, ...change }, credential, read)).rejects.toThrow('not verified');
    expect(calls.connections).toBe(1); expect(read).toHaveBeenCalledOnce();
  });

  it.each([0, 2])('rechecks the bound row on warm leases (matches=%i)', async matches => {
    const credential = token(); await withPool(binding, credential, read);
    calls.matches = matches;
    await expect(withPool(binding, credential, read)).rejects.toThrow('not bound');
    expect(read).toHaveBeenCalledOnce(); expect(calls.closes).toEqual([0]);
    calls.matches = 1;
    await withPool(binding, credential, read);
    expect(calls.connections).toBe(2);
  });

  it('rechecks expected tables on warm leases', async () => {
    const credential = token(); await withPool(binding, credential, read);
    calls.tables = operationalTables.filter(name => name !== 'Rentals');
    await expect(withPool(binding, credential, read)).rejects.toThrow('tables are missing');
    expect(read).toHaveBeenCalledOnce(); expect(calls.closes).toEqual([0]);
  });

  it('retains physical connections for five minutes from the last completed read, without keepalive', async () => {
    const credential = token(); await withPool(binding, credential, read);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(calls.connections).toBe(1); expect(calls.requests).toHaveLength(2); expect(calls.closes).toEqual([]);
    await withPool(binding, credential, read);
    await vi.advanceTimersByTimeAsync(299_999); expect(calls.closes).toEqual([]);
    await vi.advanceTimersByTimeAsync(1); expect(calls.closes).toEqual([0]);
    await withPool(binding, credential, read); expect(calls.connections).toBe(2);
  });

  it('bounds warm pool lifetime to fifteen minutes', async () => {
    const credential = token();
    for (let i = 0; i < 5; i++) {
      await withPool(binding, credential, read);
      expect(calls.connections).toBe(1);
      await vi.advanceTimersByTimeAsync(180_000);
    }
    expect(calls.closes).toEqual([0]);
    await withPool(binding, credential, read); expect(calls.connections).toBe(2);
  });

  it('drains an expired active lease without closing it under its reader', async () => {
    const gate = deferred(); const credential = token('short', 80);
    const pending = withPool(binding, credential, () => gate.promise);
    await flush();
    await vi.advanceTimersByTimeAsync(20_000);
    expect(calls.closes).toEqual([]);
    await withPool(binding, credential, read);
    expect(calls.connections).toBe(2); expect(calls.closes).toEqual([1]);
    gate.resolve(); await pending; expect(calls.closes).toEqual([1, 0]);
  });

  it('does not cache opaque, missing-expiry, or nearly expired credentials and rejects expired ones', async () => {
    for (const credential of ['opaque', 'header.e30.signature', token('near', 30)]) {
      await withPool(binding, credential, read);
      await withPool(binding, credential, read);
    }
    expect(calls.connections).toBe(6); expect(calls.closes).toHaveLength(6);
    await expect(withPool(binding, token('expired', -1), read)).rejects.toThrow('expired');
    expect(calls.connections).toBe(6);
  });

  it('does not start SQL validation or work if the token expires during connection setup', async () => {
    const gate = deferred(); calls.connectDelay = gate.promise;
    const pending = withPool(binding, token('short', 5), read);
    const failed = expect(pending).rejects.toThrow('expired');
    await vi.advanceTimersByTimeAsync(6000);
    gate.resolve(); await failed;
    expect(calls.requests).toHaveLength(0); expect(read).not.toHaveBeenCalled(); expect(calls.closes).toEqual([0]);
  });

  it('bounds all live pools, including active, retiring and asynchronously closing entries', async () => {
    const gates = Array.from({ length: 4 }, () => deferred());
    const active = gates.map((gate, index) => withPool(binding, token(String(index)), () => gate.promise));
    await flush(); expect(calls.connections).toBe(4);
    const close = deferred(); calls.closeDelay = close.promise;
    const waiting = withPool(binding, token('fifth'), read);
    await flush(); expect(calls.connections).toBe(4); expect(read).not.toHaveBeenCalled();
    gates[0].resolve(); await active[0]; await flush();
    expect(calls.closes).toEqual([0]); expect(calls.connections).toBe(4);
    close.resolve(); await waiting;
    expect(calls.connections).toBe(5); expect(read).toHaveBeenCalledOnce();
    gates.slice(1).forEach(gate => gate.resolve()); await Promise.all(active);
  });

  it('evicts the least recently released idle entry, never an active reader', async () => {
    for (let i = 0; i < 4; i++) {
      await withPool(binding, token(String(i)), read);
      await vi.advanceTimersByTimeAsync(1);
    }
    const gate = deferred();
    const active = withPool(binding, token('0'), () => gate.promise);
    await flush();
    await withPool(binding, token('fifth'), read);
    expect(calls.closes).toEqual([1]); expect(calls.connections).toBe(5);
    gate.resolve(); await active;
  });

  it('bounds acquisition waiters and removes timed-out waiters', async () => {
    const gates = Array.from({ length: 4 }, () => deferred());
    const active = gates.map((gate, index) => withPool(binding, token(String(index)), () => gate.promise));
    await flush();
    const waiting = Array.from({ length: 32 }, (_, index) =>
      withPool(binding, token(`waiting-${index}`), read).then(() => 'unexpected success', error => error.message));
    await expect(withPool(binding, token('overflow'), read)).rejects.toThrow('busy');
    await vi.advanceTimersByTimeAsync(15_000);
    expect(await Promise.all(waiting)).toEqual(Array(32).fill('Operational SQL pool acquisition timed out.'));
    expect(calls.connections).toBe(4); expect(read).not.toHaveBeenCalled();
    gates.forEach(gate => gate.resolve()); await Promise.all(active);
    await withPool(binding, token('after-timeout'), read); expect(calls.connections).toBe(5);
  });

  it('retires errors without interrupting another lease or closing its replacement', async () => {
    const credential = token(); const gate = deferred();
    const active = withPool(binding, credential, () => gate.promise);
    await flush();
    await expect(withPool(binding, credential, async () => { throw new Error('read failed'); })).rejects.toThrow('read failed');
    expect(calls.closes).toEqual([]);
    await withPool(binding, credential, read); expect(calls.connections).toBe(2);
    calls.instances[0].emit('error', new Error('late driver error'));
    gate.resolve(); await active; expect(calls.closes).toEqual([0]);
    await withPool(binding, credential, read); expect(calls.connections).toBe(2);
  });

  it('handles background driver errors on an idle pool', async () => {
    const credential = token(); await withPool(binding, credential, read);
    calls.instances[0].emit('error', new Error('disconnected'));
    await flush(); expect(calls.closes).toEqual([0]);
    await withPool(binding, credential, read); expect(calls.connections).toBe(2);
  });

  it('cleans up a failed coalesced connection once, without replaying either read', async () => {
    const gate = deferred(); calls.connectDelay = gate.promise;
    calls.connectErrors = [Object.assign(new Error('login failed'), { code: 'ELOGIN' })];
    const credential = token();
    const failed = ['one', 'two'].map(() => expect(withPool(binding, credential, read)).rejects.toThrow('login failed'));
    await flush(); gate.resolve(); await Promise.all(failed);
    expect(calls.connections).toBe(1); expect(calls.closes).toEqual([0]); expect(read).not.toHaveBeenCalled();
    await withPool(binding, credential, read); expect(calls.connections).toBe(2);
  });

  it('retries only transient connection establishment with exponential backoff', async () => {
    calls.connectErrors = ['ETIMEOUT', 'ESOCKET'].map(code => Object.assign(new Error(code), { code }));
    const pending = withPool(binding, token(), read);
    await flush(); expect(calls.connections).toBe(1);
    await vi.advanceTimersByTimeAsync(249); expect(calls.connections).toBe(1);
    await vi.advanceTimersByTimeAsync(1); expect(calls.connections).toBe(2);
    await vi.advanceTimersByTimeAsync(500); await pending;
    expect(calls.connections).toBe(3); expect(read).toHaveBeenCalledOnce();
  });

  it('preserves the original read failure if closing the retired pool also fails', async () => {
    calls.closeError = new Error('close failed');
    await expect(withPool(binding, token(), async () => { throw new Error('read failed'); })).rejects.toThrow('read failed');
    expect(calls.closes).toEqual([0]);
    calls.closeError = null;
    await withPool(binding, token(), read); expect(calls.connections).toBe(2);
  });

  it('keeps command pools dedicated even when a read pool is warm', async () => {
    const credential = token(); const warm = await withPool(binding, credential, async pool => pool);
    const one = await dedicatedPool(binding, credential); const two = await dedicatedPool(binding, credential);
    expect(one).not.toBe(warm); expect(two).not.toBe(one); expect(calls.connections).toBe(3);
    expect(calls.configs[1]).toMatchObject({ pool: { min: 0, max: 2, idleTimeoutMillis: 1000 } });
    await one.close(); await two.close();
    expect(calls.closes).toEqual([1, 2]);
    await withPool(binding, credential, read); expect(calls.connections).toBe(3);
  });
});
