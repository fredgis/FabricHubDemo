import { createHash } from 'node:crypto';
import sql from 'mssql';
import type { AnalyticsBinding } from '../../data/schema.js';

const IDLE_MS = 5 * 60_000;
const MAX_AGE_MS = 15 * 60_000;
const MAX_POOLS = 4;

type Entry = {
  pool: sql.ConnectionPool;
  ready: Promise<void>;
  expiresAt: number;
  users: number;
  lastUsed: number;
  retired: boolean;
  timer?: ReturnType<typeof setTimeout>;
};
const pools = new Map<string, Entry>();

export function assertGoldBinding(binding: AnalyticsBinding): void {
  if (!binding.verified || binding.binding_key !== 'business-gold' || binding.name !== 'MSFlixGold' ||
      !binding.sql_server.endsWith('.datawarehouse.fabric.microsoft.com') ||
      binding.sql_database !== binding.item_id || !/^[a-f0-9-]{36}$/i.test(binding.item_id))
    throw new Error('Gold Warehouse binding is not verified. Operational SQL will not substitute for Gold.');
}

export function goldPool(binding: AnalyticsBinding, token: string): sql.ConnectionPool {
  assertGoldBinding(binding);
  return new sql.ConnectionPool({ server: binding.sql_server, database: binding.sql_database,
    options: { encrypt: true, trustServerCertificate: false },
    authentication: { type: 'azure-active-directory-access-token', options: { token } },
    connectionTimeout: 15000, requestTimeout: 30000,
    pool: { min: 0, max: 2, idleTimeoutMillis: IDLE_MS } });
}

export async function connectGoldPool(pool: sql.ConnectionPool): Promise<void> {
  for (let attempt = 0; ; attempt++) {
    try { await pool.connect(); return; }
    catch (error) {
      if (attempt >= 2 || !['ETIMEOUT', 'ESOCKET', 'ECONNRESET'].includes((error as { code?: string }).code ?? '')) throw error;
      await new Promise(resolve => setTimeout(resolve, 250 * 2 ** attempt));
    }
  }
}

function reuseUntil(token: string, now: number): number {
  try {
    const { exp } = JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString()) as { exp?: unknown };
    return typeof exp === 'number' && Number.isFinite(exp) ? Math.min(exp * 1000 - 60_000, now + MAX_AGE_MS) : now;
  } catch { return now; }
}

function retire(key: string, entry: Entry): void {
  if (pools.get(key) === entry) pools.delete(key);
  if (entry.retired) return;
  entry.retired = true;
  clearTimeout(entry.timer);
  if (entry.users === 0) void entry.pool.close().catch(() => undefined);
}

export async function withGoldPool<T>(binding: AnalyticsBinding, token: string,
  read: (pool: sql.ConnectionPool) => Promise<T>): Promise<T> {
  assertGoldBinding(binding);
  const now = Date.now();
  const expiresAt = reuseUntil(token, now);
  for (const [key, entry] of pools) if (entry.expiresAt <= now) retire(key, entry);
  const key = createHash('sha256').update(JSON.stringify([
    binding.workspace_id, binding.capacity_id, binding.item_id, binding.sql_server, binding.sql_database, token,
  ])).digest('hex');
  let entry = pools.get(key);
  if (!entry && expiresAt > now && pools.size >= MAX_POOLS) {
    const idle = [...pools].filter(([, value]) => value.users === 0).sort((a, b) => a[1].lastUsed - b[1].lastUsed)[0];
    if (idle) retire(...idle);
  }
  if (!entry && expiresAt > now && pools.size < MAX_POOLS) {
    const pool = goldPool(binding, token);
    entry = { pool, ready: connectGoldPool(pool), expiresAt, users: 0, lastUsed: now, retired: false };
    const created = entry;
    pool.on('error', () => retire(key, created));
    pools.set(key, entry);
  }
  if (!entry) {
    const pool = goldPool(binding, token);
    try { await connectGoldPool(pool); return await read(pool); }
    finally { await pool.close(); }
  }
  clearTimeout(entry.timer);
  entry.users++;
  try {
    await entry.ready;
    return await read(entry.pool);
  } catch (error) {
    retire(key, entry);
    throw error;
  } finally {
    entry.users--;
    if (entry.retired) {
      if (entry.users === 0) void entry.pool.close().catch(() => undefined);
    } else if (entry.users === 0) {
      entry.lastUsed = Date.now();
      const released = entry;
      entry.timer = setTimeout(() => retire(key, released), Math.max(0, Math.min(IDLE_MS, entry.expiresAt - entry.lastUsed)));
      entry.timer.unref();
    }
  }
}
