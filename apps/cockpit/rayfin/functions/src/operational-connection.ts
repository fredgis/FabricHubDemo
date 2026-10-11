import { createHash } from 'node:crypto';
import sql from 'mssql';
import type { RuntimeBinding } from '../../data/schema.js';

const IDLE_MS = 5 * 60_000;
const MAX_AGE_MS = 15 * 60_000;
const MAX_POOLS = 4;
const ACQUIRE_TIMEOUT_MS = 15_000;
const MAX_WAITERS = 32;
const TOKEN_SKEW_MS = 60_000;

// Identifiers are closed constants from server source, never supplied by a caller.
const TABLES = ['Contents', 'Customers', 'Offers', 'Rentals', 'Playbacks', 'Outboxes', 'ControlCommands',
  'OperatorGrants', 'RuntimeBindings', 'CommandReceipts', 'EventSequences'] as const;

export function assertOperationalBinding(binding: RuntimeBinding): void {
  if (!binding.verified || binding.binding_key !== 'app-linked-operational'
    || !binding.sql_server.endsWith('.database.fabric.microsoft.com'))
    throw new Error('App-linked operational SQL binding is not verified.');
}

export function operationalPool(binding: RuntimeBinding, token: string, idleTimeoutMillis = 1000): sql.ConnectionPool {
  assertOperationalBinding(binding);
  return new sql.ConnectionPool({
    server: binding.sql_server, database: binding.sql_database,
    options: { encrypt: true, trustServerCertificate: false, abortTransactionOnError: true },
    authentication: { type: 'azure-active-directory-access-token', options: { token } },
    connectionTimeout: 15000, requestTimeout: 30000,
    pool: { max: 2, min: 0, idleTimeoutMillis },
  });
}

export async function connectOperationalPool(pool: sql.ConnectionPool): Promise<void> {
  // Retry connection establishment only, never a command or a read transaction.
  for (let attempt = 0; ; attempt++) {
    try { await pool.connect(); return; }
    catch (error) {
      if (attempt === 2 || !['ETIMEOUT', 'ESOCKET', 'ECONNRESET'].includes((error as { code?: string }).code ?? '')) throw error;
      await new Promise(resolve => setTimeout(resolve, 250 * 2 ** attempt));
    }
  }
}

export async function validateOperationalPool(pool: sql.ConnectionPool, binding: RuntimeBinding): Promise<void> {
  assertOperationalBinding(binding);
  const matched = await pool.request().input('id', sql.UniqueIdentifier, binding.id)
    .input('item', sql.NVarChar(128), binding.fabric_item_id)
    .input('workspace', sql.NVarChar(128), binding.workspace_id)
    .input('capacity', sql.NVarChar(128), binding.capacity_id)
    .query(`SELECT id FROM dbo.RuntimeBindings WHERE id=@id AND fabric_item_id=@item
      AND workspace_id=@workspace AND capacity_id=@capacity AND verified=1`);
  if (matched.recordset.length !== 1) throw new Error('Connected database is not bound to this app.');
  const tables = await pool.request().query("SELECT name FROM sys.tables WHERE schema_id=SCHEMA_ID('dbo')");
  const names = new Set(tables.recordset.map((row: { name: string }) => row.name));
  if (TABLES.some(name => !names.has(name))) throw new Error('Expected operational tables are missing.');
}

type Entry = {
  key: string;
  pool: sql.ConnectionPool;
  ready: Promise<void>;
  expiresAt: number;
  users: number;
  lastUsed: number;
  retired: boolean;
  broken: boolean;
  timer?: ReturnType<typeof setTimeout>;
  closing?: Promise<void>;
};
const reusable = new Map<string, Entry>();
// Connecting, uncached, draining and closing pools also consume the bound. No overflow pools.
const live = new Set<Entry>();
const waiters = new Set<() => void>();

function tokenExpiry(token: string): number | undefined {
  try {
    const { exp } = JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString()) as { exp?: unknown };
    if (typeof exp === 'number' && Number.isFinite(exp * 1000)) return exp * 1000;
  } catch { /* Opaque tokens can connect, but cannot be reused safely. */ }
}

function signal(): void { for (const wake of waiters) wake(); }

function closeIdle(entry: Entry): Promise<void> | undefined {
  if (entry.users !== 0) return;
  entry.closing ??= (async () => {
    try { await entry.pool.close(); }
    catch { /* A broken pool must not mask the original request failure. */ }
    finally { live.delete(entry); signal(); }
  })();
  return entry.closing;
}

function retire(entry: Entry): void {
  if (reusable.get(entry.key) === entry) reusable.delete(entry.key);
  entry.retired = true;
  clearTimeout(entry.timer);
  void closeIdle(entry);
}

function scheduleRetirement(entry: Entry, idle = false): void {
  clearTimeout(entry.timer);
  entry.timer = setTimeout(() => retire(entry), Math.max(0,
    Math.min(idle ? IDLE_MS : MAX_AGE_MS, entry.expiresAt - Date.now())));
  entry.timer.unref();
}

function waitForPool(deadline: number): Promise<void> {
  if (waiters.size >= MAX_WAITERS || Date.now() >= deadline)
    return Promise.reject(new Error('Operational SQL pool is busy. Try the read again shortly.'));
  return new Promise((resolve, reject) => {
    const wake = () => { clearTimeout(timer); waiters.delete(wake); resolve(); };
    const timer = setTimeout(() => {
      waiters.delete(wake);
      reject(new Error('Operational SQL pool acquisition timed out.'));
    }, deadline - Date.now());
    waiters.add(wake);
  });
}

async function acquire(binding: RuntimeBinding, token: string, tokenExpiresAt: number | undefined): Promise<Entry> {
  const deadline = Date.now() + ACQUIRE_TIMEOUT_MS;
  const key = createHash('sha256').update(JSON.stringify([
    binding.id, binding.binding_key, binding.verified, binding.sql_server, binding.sql_database,
    binding.fabric_item_id, binding.workspace_id, binding.capacity_id, token,
  ])).digest('hex');
  for (;;) {
    const now = Date.now();
    if (tokenExpiresAt !== undefined && tokenExpiresAt <= now)
      throw new Error('Operational SQL token has expired.');
    for (const entry of reusable.values()) if (entry.expiresAt <= now) retire(entry);
    const existing = reusable.get(key);
    if (existing) {
      existing.users++;
      scheduleRetirement(existing);
      return existing;
    }
    if (live.size < MAX_POOLS) {
      const expiresAt = Math.min((tokenExpiresAt ?? now) - TOKEN_SKEW_MS, now + MAX_AGE_MS);
      const pool = operationalPool(binding, token, IDLE_MS);
      const entry: Entry = { key, pool, ready: Promise.resolve(), expiresAt, users: 1,
        lastUsed: now, retired: expiresAt <= now, broken: false };
      live.add(entry);
      pool.on('error', () => { entry.broken = true; retire(entry); });
      if (!entry.retired) { reusable.set(key, entry); scheduleRetirement(entry); }
      entry.ready = connectOperationalPool(pool);
      return entry;
    }
    const idle = [...reusable.values()].filter(entry => entry.users === 0)
      .sort((a, b) => a.lastUsed - b.lastUsed)[0];
    if (idle) retire(idle);
    if (live.size < MAX_POOLS) continue;
    await waitForPool(deadline);
  }
}

/** Read-only operational lease. Caller binding/table validation is never cached. */
export async function withOperationalPool<T>(binding: RuntimeBinding, token: string,
  read: (pool: sql.ConnectionPool) => Promise<T>): Promise<T> {
  const target = { ...binding };
  assertOperationalBinding(target);
  const expiresAt = tokenExpiry(token);
  const entry = await acquire(target, token, expiresAt);
  try {
    await entry.ready;
    if (entry.broken) throw new Error('Operational SQL connection is no longer available.');
    if (expiresAt !== undefined && expiresAt <= Date.now()) throw new Error('Operational SQL token has expired.');
    await validateOperationalPool(entry.pool, target);
    if (entry.broken) throw new Error('Operational SQL connection is no longer available.');
    if (expiresAt !== undefined && expiresAt <= Date.now()) throw new Error('Operational SQL token has expired.');
    return await read(entry.pool);
  } catch (error) {
    entry.broken = true;
    retire(entry);
    throw error;
  } finally {
    entry.users--;
    if (entry.users === 0) {
      if (entry.retired) await closeIdle(entry);
      else {
        entry.lastUsed = Date.now();
        scheduleRetirement(entry, true);
        signal();
      }
    }
  }
}
