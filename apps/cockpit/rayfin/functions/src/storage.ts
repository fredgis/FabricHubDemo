import { createHash, randomUUID } from 'node:crypto';
import sql from 'mssql';
import type { RuntimeBinding, OperatorGrant } from '../../data/schema.js';
import { canonical, key, type CommandResult } from './domain.js';

export type Store = { tx: sql.Transaction; now: Date; runId: string; correlationId: string };
export type StoredEvent = { event_id: string; event_type: string; schema_version: number;
  entity_key: string; source_sequence: number; occurred_at: string; produced_at: string;
  run_id: string; correlation_id: string; payload: Record<string, unknown>; payload_json: string };

export function request(store: Store): sql.Request { return new sql.Request(store.tx); }
export function input(req: sql.Request, name: string, value: unknown): sql.Request {
  if (value === undefined || value === null) return req.input(name, sql.NVarChar(4000), null);
  if (value instanceof Date) return req.input(name, sql.DateTime2, value);
  if (typeof value === 'number') return req.input(name, sql.Int, value);
  if (typeof value === 'boolean') return req.input(name, sql.Bit, value);
  return req.input(name, sql.NVarChar(4000), String(value));
}

// Identifiers are closed constants from server source, never supplied by a caller.
const TABLES = ['Contents', 'Customers', 'Offers', 'Rentals', 'Playbacks', 'Outboxes', 'ControlCommands',
  'OperatorGrants', 'RuntimeBindings', 'CommandReceipts', 'EventSequences'] as const;
export async function poolFor(binding: RuntimeBinding, token: string): Promise<sql.ConnectionPool> {
  if (!binding.verified || binding.binding_key !== 'app-linked-operational'
    || !binding.sql_server.endsWith('.database.fabric.microsoft.com'))
    throw new Error('App-linked operational SQL binding is not verified.');
  const pool = new sql.ConnectionPool({
    server: binding.sql_server, database: binding.sql_database,
    options: { encrypt: true, trustServerCertificate: false, abortTransactionOnError: true },
    authentication: { type: 'azure-active-directory-access-token', options: { token } },
    connectionTimeout: 15000, requestTimeout: 30000,
    pool: { max: 2, min: 0, idleTimeoutMillis: 1000 },
  });
  // Retry connection establishment only. Never retry a mutation with a new key.
  try {
    for (let attempt = 0; ; attempt++) {
      try { await pool.connect(); break; }
      catch (error) {
        if (attempt === 2 || !['ETIMEOUT', 'ESOCKET', 'ECONNRESET'].includes((error as { code?: string }).code ?? '')) throw error;
        await new Promise(resolve => setTimeout(resolve, 250 * 2 ** attempt));
      }
    }
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
    return pool;
  } catch (error) { await pool.close(); throw error; }
}

export async function atomic<T extends CommandResult>(pool: sql.ConnectionPool, grant: OperatorGrant, idempotencyKey: string,
  operation: string, parameters: unknown, work: (store: Store) => Promise<T>,
  metadata?: { runId: string }): Promise<T> {
  key(idempotencyKey, 'idempotency key');
  const fingerprint = createHash('sha256').update(canonical({ operation, parameters, user_id: grant.user_id })).digest('hex');
  const tx = new sql.Transaction(pool);
  await tx.begin(sql.ISOLATION_LEVEL.SERIALIZABLE);
  const store: Store = { tx, now: new Date(), runId: metadata?.runId ?? randomUUID(), correlationId: idempotencyKey };
  try {
    const valid = await request(store).input('id', sql.UniqueIdentifier, grant.id)
      .input('user', sql.NVarChar(128), grant.user_id).input('now', sql.DateTime2, store.now)
      .query('SELECT id FROM dbo.OperatorGrants WITH (UPDLOCK,HOLDLOCK) WHERE id=@id AND user_id=@user AND enabled=1 AND expires_at>@now');
    if (valid.recordset.length !== 1) throw new Error('Operator permission expired or revoked.');
    const previous = await request(store).input('key', sql.NVarChar(128), idempotencyKey)
      .query('SELECT fingerprint,result_json FROM dbo.CommandReceipts WITH (UPDLOCK,HOLDLOCK) WHERE idempotency_key=@key');
    if (previous.recordset.length) {
      if (previous.recordset[0].fingerprint !== fingerprint) throw new Error('Idempotency key already belongs to a different command.');
      await tx.commit();
      return JSON.parse(previous.recordset[0].result_json) as T;
    }

    const result = await work(store);
    await request(store).input('id', sql.UniqueIdentifier, randomUUID()).input('key', sql.NVarChar(128), idempotencyKey)
      .input('fingerprint', sql.NVarChar(64), fingerprint).input('user', sql.NVarChar(128), grant.user_id)
      .input('result', sql.NVarChar(4000), canonical(result)).input('now', sql.DateTime2, store.now)
      .query(`INSERT dbo.CommandReceipts (id,idempotency_key,fingerprint,user_id,result_json,created_at)
        VALUES (@id,@key,@fingerprint,@user,@result,@now)`);
    await tx.commit();
    return result;
  } catch (error) {
    try { await tx.rollback(); } catch { /* XACT_ABORT may already have rolled back. */ }
    throw error;
  }
}

export type StateChange = { event_type: string; entity_key: string; payload: Record<string, unknown>; event_id?: string };
export async function emitMany(store: Store, changes: StateChange[]): Promise<{ first_sequence: number; last_sequence: number }> {
  if (changes.length < 1 || changes.length > 1900) throw new Error('Outbox batch must contain 1-1900 committed state changes.');
  const rows = changes.map((change, offset) => {
    key(change.entity_key, 'event entity key');
    const json = canonical(change.payload);
    if (json.length > 4000) throw new Error('Event state exceeds outbox payload limit.');
    return { offset, event_id: change.event_id ?? randomUUID(), event_type: change.event_type,
      entity_key: change.entity_key, payload_json: json };
  });
  const sequence = await request(store).input('count', sql.Int, rows.length).query(`
    UPDATE dbo.EventSequences WITH (UPDLOCK,HOLDLOCK) SET value=value+@count
    OUTPUT INSERTED.value WHERE sequence_key='operational'`);
  if (!sequence.recordset.length) throw new Error('Operational event sequence has not been initialized.');
  const last = sequence.recordset[0].value as number;
  const first = last - rows.length + 1;
  await request(store).input('events', sql.NVarChar(sql.MAX), JSON.stringify(rows))
    .input('first', sql.Int, first).input('now', sql.DateTime2, store.now)
    .input('run', sql.NVarChar(128), store.runId).input('correlation', sql.NVarChar(128), store.correlationId)
    .query(`INSERT dbo.Outboxes (id,event_id,event_type,schema_version,entity_key,source_sequence,
      occurred_at,produced_at,run_id,correlation_id,payload,payload_json,published_at)
      SELECT CONVERT(uniqueidentifier,event_id),event_id,event_type,1,entity_key,@first+ordinal,
        @now,@now,@run,@correlation,payload_json,payload_json,NULL
      FROM OPENJSON(@events) WITH (ordinal int '$.offset',event_id nvarchar(128),
        event_type nvarchar(80),entity_key nvarchar(128),payload_json nvarchar(4000))`);
  return { first_sequence: first, last_sequence: last };
}

export async function emit(store: Store, eventType: string, entityKey: string,
  payload: Record<string, unknown>): Promise<string> {
  // Sequence increment, business row and event are committed in the same transaction.
  const sequence = await request(store).query(`UPDATE dbo.EventSequences WITH (UPDLOCK,HOLDLOCK)
    SET value=value+1 OUTPUT INSERTED.value WHERE sequence_key='operational'`);
  if (!sequence.recordset.length) throw new Error('Operational event sequence has not been initialized.');
  const eventId = randomUUID();
  const payloadJson = canonical(payload);
  if (payloadJson.length > 4000) throw new Error('Event state exceeds outbox payload limit.');
  await request(store).input('id', sql.UniqueIdentifier, eventId)
    .input('event', sql.NVarChar(128), eventId).input('type', sql.NVarChar(80), eventType)
    .input('entity', sql.NVarChar(128), entityKey).input('sequence', sql.Int, sequence.recordset[0].value)
    .input('now', sql.DateTime2, store.now).input('run', sql.NVarChar(128), store.runId)
    .input('correlation', sql.NVarChar(128), store.correlationId)
    .input('payload', sql.NVarChar(4000), payloadJson)
    .query(`INSERT dbo.Outboxes (id,event_id,event_type,schema_version,entity_key,source_sequence,
      occurred_at,produced_at,run_id,correlation_id,payload,payload_json,published_at)
      VALUES (@id,@event,@type,1,@entity,@sequence,@now,@now,@run,@correlation,@payload,@payload,NULL)`);
  return eventId;
}

export function publicState(row: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(row).filter(([name]) => name !== 'id')
    .map(([name, value]) => [name, value instanceof Date ? value.toISOString() : value]));
}
