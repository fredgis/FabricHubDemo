import sql from 'mssql';
import type { OperatorGrant } from '../../data/schema.js';
import { atomic, emitMany, request, type Store } from './storage.js';
import { batchKey, digest, stableUuid, validateBatch, validateProfile,
  type BatchResult, type VolumeProfile } from './volume-domain.js';

export type RunContract = { profile: VolumeProfile; source_manifest_hash: string; policy_hash: string;
  lease_id: string; max_pending_events?: number };
export function runFingerprint(run: Omit<RunContract, 'lease_id'>): string {
  if (![run.source_manifest_hash, run.policy_hash].every(x => /^[a-f0-9]{64}$/.test(x)))
    throw new Error('Source/policy hashes must be SHA-256.');
  return digest({ profile: validateProfile(run.profile), source_manifest_hash: run.source_manifest_hash, policy_hash: run.policy_hash });
}

/**
 * Trusted worker-only command. One receipt covers a bounded, immutable chunk.
 * The shared atomic core checks the operator grant and serializable replay.
 * Prices, windows and duration are resolved inside the SQL transaction.
 */
export async function bulkSourceTransactions(pool: sql.ConnectionPool, grant: OperatorGrant,
  run: RunContract, index: number, input: unknown): Promise<BatchResult> {
  const p = validateProfile(run.profile);
  const rows = validateBatch(p, index, input);
  const fingerprint = runFingerprint(run);
  return atomic(pool, grant, batchKey(p.run_key, index), 'bulkSourceTransactions',
    { fingerprint, index, rows }, async store => {
      const state = await request(store).input('run', sql.NVarChar(64), p.run_key)
        .input('fingerprint', sql.NVarChar(64), fingerprint)
        .query('SELECT * FROM dbo.VolumeRuns WITH (UPDLOCK,HOLDLOCK) WHERE run_key=@run');
      const current = state.recordset[0];
      if (!current || current.user_id !== grant.user_id || current.fingerprint !== fingerprint)
        throw new Error('Run owner, profile or source manifest changed.');
      if (current.status !== 'running' || current.cancel_requested || current.lease_id !== run.lease_id
          || new Date(current.lease_expires_at).getTime() <= store.now.getTime())
        throw new Error('Volume run is paused, cancelled or its worker lease expired.');
      const maxPending = run.max_pending_events ?? 20000;
      if (!Number.isInteger(maxPending) || maxPending < 1000 || maxPending > 100000)
        throw new Error('Pending outbox limit must be 1000-100000.');
      const expected = rows.length * (3 + p.progress_updates);
      const pending = await request(store).query('SELECT COUNT(*) AS pending FROM dbo.Outboxes WHERE published_at IS NULL');
      if (!Number.isInteger(pending.recordset[0]?.pending)) throw new Error('Outbox backlog check failed.');
      if (pending.recordset[0].pending + expected > maxPending)
        throw Object.assign(new Error('Publisher backlog reached the bounded pending-event limit.'), { code: 'VOLUME_BACKLOG_LIMIT' });
      const prepared = rows.map((row, ordinal) => ({ ...row, ordinal,
        order_id: stableUuid(`${p.run_key}:order:${row.source_transaction_key}`),
        session_id: stableUuid(`${p.run_key}:session:${row.source_transaction_key}`),
      }));
      const changes = await writeSourceBatch(store, prepared, p.progress_updates);
      if (changes.length !== expected) throw new Error('Persisted source-change count does not match the batch contract.');
      const sequences = await emitMany(store, changes.map(row => ({
        event_type: row.event_type, entity_key: row.entity_key,
        event_id: stableUuid(`${p.run_key}:event:${row.source_transaction_key}:${row.phase}`),
        payload: JSON.parse(row.payload_json) as Record<string, unknown>,
      })));
      await request(store).input('run', sql.NVarChar(64), p.run_key).input('orders', sql.Int, rows.length)
        .input('events', sql.Int, changes.length).input('now', sql.DateTime2, store.now).query(`
          UPDATE dbo.VolumeRuns SET committed_orders=committed_orders+@orders,
            committed_events=committed_events+@events,committed_batches=committed_batches+1,
            updated_at=@now,lease_expires_at=DATEADD(second,120,@now)
          WHERE run_key=@run`);
      return { entity_key: p.run_key, status: 'committed', event_ids: [],
        orders: rows.length, events: changes.length, batch_index: index, ...sequences };
    }, { runId: p.run_key });
}

type Change = { phase: number; source_transaction_key: string; event_type: string; entity_key: string; payload_json: string };
type Prepared = { source_transaction_key: string; ordinal: number; customer_key: string; offer_key: string; order_id: string; session_id: string };
export async function writeSourceBatch(store: Store, rows: Prepared[], progress: number): Promise<Change[]> {
  const result = await request(store).input('input', sql.NVarChar(sql.MAX), JSON.stringify(rows))
    .input('progress', sql.Int, progress).input('now', sql.DateTime2, store.now).query(BULK_SQL);
  return result.recordset as Change[];
}

// All statements use actual INSERT/UPDATE OUTPUT row states. No event-only rows
// are generated. JSON is only a parameterized transport for bounded input/state.
const BULK_SQL = `
/* bulk-source-transactions */
SET NOCOUNT ON;
DECLARE @Source TABLE (ordinal int PRIMARY KEY,source_transaction_key nvarchar(128) UNIQUE,
  customer_key nvarchar(128),offer_key nvarchar(128),order_id nvarchar(128),session_id nvarchar(128));
INSERT @Source SELECT ordinal,source_transaction_key,customer_key,offer_key,order_id,session_id
  FROM OPENJSON(@input) WITH (ordinal int,source_transaction_key nvarchar(128),
    customer_key nvarchar(128),offer_key nvarchar(128),order_id nvarchar(128),session_id nvarchar(128));
DECLARE @Eligible TABLE (ordinal int PRIMARY KEY,source_transaction_key nvarchar(128),
  customer_key nvarchar(128),offer_key nvarchar(128),order_id nvarchar(128),session_id nvarchar(128),
  content_key nvarchar(128),transaction_type nvarchar(16),amount_minor int,currency nvarchar(3),
  start_hours int,play_hours int,duration int);
INSERT @Eligible SELECT s.ordinal,s.source_transaction_key,s.customer_key,s.offer_key,s.order_id,s.session_id,
  o.content_key,o.transaction_type,o.price_minor,o.currency,o.start_window_hours,o.play_window_hours,c.duration_seconds
  FROM @Source s JOIN dbo.Customers customer WITH (HOLDLOCK) ON customer.customer_key=s.customer_key
  JOIN dbo.Offers o WITH (HOLDLOCK) ON o.offer_key=s.offer_key AND o.territory=customer.territory
  JOIN dbo.Contents c WITH (HOLDLOCK) ON c.content_key=o.content_key;
IF (SELECT COUNT(*) FROM @Eligible)<>(SELECT COUNT(*) FROM @Source)
  THROW 50001,'Missing customer, offer, film or matching territory.',1;
IF EXISTS (SELECT 1 FROM @Eligible WHERE transaction_type NOT IN ('TVOD','EST')
  OR amount_minor<0 OR currency COLLATE Latin1_General_100_BIN2 NOT LIKE '[A-Z][A-Z][A-Z]'
  OR LEN(currency)<>3 OR duration<@progress
  OR (transaction_type='TVOD' AND (start_hours NOT BETWEEN 1 AND 8760 OR play_hours NOT BETWEEN 1 AND 8760)))
  THROW 50002,'Invalid server offer policy or duration for strictly increasing progress.',1;

DECLARE @Orders TABLE (order_id nvarchar(128),customer_key nvarchar(128),offer_key nvarchar(128),
  status nvarchar(24),amount_minor int,currency nvarchar(3),created_at datetime2,
  start_deadline datetime2,first_play_at datetime2,expires_at datetime2);
DECLARE @Playback TABLE (session_id nvarchar(128),order_id nvarchar(128),content_key nvarchar(128),
  customer_key nvarchar(128),position_seconds int,status nvarchar(24));
DECLARE @Changes TABLE (ordinal int,phase int,source_transaction_key nvarchar(128),
  event_type nvarchar(80),entity_key nvarchar(128),payload_json nvarchar(max));

INSERT dbo.Rentals (id,order_id,customer_key,offer_key,status,amount_minor,currency,
  created_at,start_deadline,first_play_at,expires_at)
OUTPUT INSERTED.order_id,INSERTED.customer_key,INSERTED.offer_key,INSERTED.status,
  INSERTED.amount_minor,INSERTED.currency,INSERTED.created_at,INSERTED.start_deadline,
  INSERTED.first_play_at,INSERTED.expires_at INTO @Orders
SELECT CONVERT(uniqueidentifier,order_id),order_id,customer_key,offer_key,
  CASE WHEN transaction_type='EST' THEN 'purchased' ELSE 'booked' END,amount_minor,currency,
  @now,CASE WHEN transaction_type='TVOD' THEN DATEADD(hour,start_hours,@now) ELSE NULL END,NULL,NULL
FROM @Eligible;
INSERT @Changes SELECT e.ordinal,0,e.source_transaction_key,'rental.created',r.order_id,
  (SELECT r.order_id,r.customer_key,r.offer_key,r.status,r.amount_minor,r.currency,
    CONVERT(nvarchar(33),r.created_at,127)+'Z' AS created_at,
    CONVERT(nvarchar(33),r.start_deadline,127)+'Z' AS start_deadline,
    CONVERT(nvarchar(33),r.first_play_at,127)+'Z' AS first_play_at,
    CONVERT(nvarchar(33),r.expires_at,127)+'Z' AS expires_at FOR JSON PATH,WITHOUT_ARRAY_WRAPPER,INCLUDE_NULL_VALUES)
  FROM @Orders r JOIN @Eligible e ON e.order_id=r.order_id;
DELETE FROM @Orders;

UPDATE r SET first_play_at=@now,
  expires_at=CASE WHEN e.transaction_type='TVOD' THEN DATEADD(hour,e.play_hours,@now) ELSE NULL END,
  status=CASE WHEN e.transaction_type='TVOD' THEN 'active' ELSE 'purchased' END
OUTPUT INSERTED.order_id,INSERTED.customer_key,INSERTED.offer_key,INSERTED.status,
  INSERTED.amount_minor,INSERTED.currency,INSERTED.created_at,INSERTED.start_deadline,
  INSERTED.first_play_at,INSERTED.expires_at INTO @Orders
FROM dbo.Rentals r JOIN @Eligible e ON e.order_id=r.order_id
WHERE r.status IN ('booked','purchased') AND r.first_play_at IS NULL
  AND (e.transaction_type='EST' OR r.start_deadline>@now);
IF (SELECT COUNT(*) FROM @Orders)<>(SELECT COUNT(*) FROM @Eligible)
  THROW 50003,'New entitlement is not playable.',1;
INSERT @Changes SELECT e.ordinal,1,e.source_transaction_key,'rental.updated',r.order_id,
  (SELECT r.order_id,r.customer_key,r.offer_key,r.status,r.amount_minor,r.currency,
    CONVERT(nvarchar(33),r.created_at,127)+'Z' AS created_at,
    CONVERT(nvarchar(33),r.start_deadline,127)+'Z' AS start_deadline,
    CONVERT(nvarchar(33),r.first_play_at,127)+'Z' AS first_play_at,
    CONVERT(nvarchar(33),r.expires_at,127)+'Z' AS expires_at FOR JSON PATH,WITHOUT_ARRAY_WRAPPER,INCLUDE_NULL_VALUES)
  FROM @Orders r JOIN @Eligible e ON e.order_id=r.order_id;

INSERT dbo.Playbacks (id,session_id,order_id,content_key,customer_key,position_seconds,status)
OUTPUT INSERTED.session_id,INSERTED.order_id,INSERTED.content_key,INSERTED.customer_key,
  INSERTED.position_seconds,INSERTED.status INTO @Playback
SELECT CONVERT(uniqueidentifier,session_id),session_id,order_id,content_key,customer_key,0,'playing' FROM @Eligible;
INSERT @Changes SELECT e.ordinal,2,e.source_transaction_key,'playback.created',p.session_id,
  (SELECT p.session_id,p.order_id,p.content_key,p.customer_key,p.position_seconds,p.status
    FOR JSON PATH,WITHOUT_ARRAY_WRAPPER,INCLUDE_NULL_VALUES)
  FROM @Playback p JOIN @Eligible e ON e.session_id=p.session_id;
DELETE FROM @Playback;

DECLARE @Step int=1;
WHILE @Step<=@progress
BEGIN
  UPDATE p SET position_seconds=CONVERT(int,CONVERT(bigint,e.duration)*@Step/@progress),
    status=CASE WHEN @Step=@progress THEN 'completed' ELSE 'playing' END
  OUTPUT INSERTED.session_id,INSERTED.order_id,INSERTED.content_key,INSERTED.customer_key,
    INSERTED.position_seconds,INSERTED.status INTO @Playback
  FROM dbo.Playbacks p JOIN @Eligible e ON e.session_id=p.session_id
  JOIN dbo.Rentals r ON r.order_id=e.order_id
  WHERE p.position_seconds<CONVERT(int,CONVERT(bigint,e.duration)*@Step/@progress)
    AND r.status IN ('active','purchased')
    AND (e.transaction_type='EST' OR r.expires_at>@now);
  IF (SELECT COUNT(*) FROM @Playback)<>(SELECT COUNT(*) FROM @Eligible)
    THROW 50004,'Progress exceeds entitlement or is not strictly increasing.',1;
  INSERT @Changes SELECT e.ordinal,2+@Step,e.source_transaction_key,'playback.updated',p.session_id,
    (SELECT p.session_id,p.order_id,p.content_key,p.customer_key,p.position_seconds,p.status
      FOR JSON PATH,WITHOUT_ARRAY_WRAPPER,INCLUDE_NULL_VALUES)
    FROM @Playback p JOIN @Eligible e ON e.session_id=p.session_id;
  DELETE FROM @Playback;
  SET @Step=@Step+1;
END;
SELECT phase,source_transaction_key,event_type,entity_key,payload_json
FROM @Changes ORDER BY phase,ordinal;
`;
