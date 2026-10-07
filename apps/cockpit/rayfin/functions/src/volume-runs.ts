import { randomUUID } from 'node:crypto';
import sql from 'mssql';
import type { OperatorGrant, VolumeRun } from '../../data/schema.js';
import { atomic, request } from './storage.js';
import { canonical } from './domain.js';
import { runFingerprint, type RunContract } from './volume-batch.js';
import { stableUuid, volumeEstimate } from './volume-domain.js';

export async function initializeRun(pool: sql.ConnectionPool, grant: OperatorGrant, run: RunContract): Promise<void> {
  const fingerprint = runFingerprint(run);
  const { orders, events } = volumeEstimate(run.profile);
  await atomic(pool, grant, `volume:${run.profile.run_key}:init`, 'initializeVolumeRun',
    { fingerprint }, async store => {
      await request(store).input('id', sql.UniqueIdentifier, stableUuid(`volume-run:${run.profile.run_key}`))
        .input('run', sql.NVarChar(64), run.profile.run_key).input('user', sql.NVarChar(128), grant.user_id)
        .input('hash', sql.NVarChar(64), fingerprint).input('profile', sql.NVarChar(4000), canonical(run.profile))
        .input('manifest', sql.NVarChar(64), run.source_manifest_hash).input('policy', sql.NVarChar(64), run.policy_hash)
        .input('orders', sql.Int, orders).input('events', sql.Int, events).input('now', sql.DateTime2, store.now)
        .query(`INSERT dbo.VolumeRuns (id,run_key,user_id,fingerprint,profile_json,source_manifest_hash,
          policy_hash,status,total_orders,total_events,committed_orders,committed_events,committed_batches,
          cancel_requested,lease_id,lease_expires_at,requested_at,updated_at)
          VALUES (@id,@run,@user,@hash,@profile,@manifest,@policy,'paused',@orders,@events,0,0,0,0,NULL,NULL,@now,@now)`);
      return { entity_key: run.profile.run_key, status: 'initialized', event_ids: [] };
    }, { runId: run.profile.run_key });
}

export async function transitionRun(pool: sql.ConnectionPool, grant: OperatorGrant, run: RunContract,
  action: 'acquire' | 'pause' | 'cancel' | 'complete'): Promise<void> {
  const fingerprint = runFingerprint(run);
  await atomic(pool, grant, `volume:${run.profile.run_key}:control:${randomUUID()}`, 'controlVolumeRun',
    { fingerprint, action, lease: run.lease_id }, async store => {
      const result = await request(store).input('run', sql.NVarChar(64), run.profile.run_key)
        .query('SELECT * FROM dbo.VolumeRuns WITH (UPDLOCK,HOLDLOCK) WHERE run_key=@run');
      const current = result.recordset[0] as VolumeRun | undefined;
      if (!current || current.fingerprint !== fingerprint || current.user_id !== grant.user_id)
        throw new Error('Run owner or immutable manifest/profile does not match.');
      const ownsLease = current.lease_id === run.lease_id;
      const liveLease = current.status === 'running' && current.lease_expires_at &&
        new Date(current.lease_expires_at).getTime() > store.now.getTime();
      if (action === 'acquire') {
        if (current.cancel_requested || current.status === 'cancelled') throw new Error('Run is cancelled; use a new run key for new work.');
        if (current.status === 'completed') throw new Error('Run has already completed.');
        if (liveLease && !ownsLease) throw new Error('Another worker owns the active run lease.');
      } else if (action !== 'cancel' && !ownsLease) throw new Error('Worker does not own this run lease.');
      if (action === 'complete' && (current.cancel_requested || current.committed_orders !== current.total_orders ||
          current.committed_events !== current.total_events || current.committed_batches !== volumeEstimate(run.profile).batches))
        throw new Error('Incomplete or cancelled run cannot be marked completed.');
      await request(store).input('run', sql.NVarChar(64), run.profile.run_key)
        .input('status', sql.NVarChar(24), action === 'acquire' ? 'running' : action === 'complete' ? 'completed' :
          action === 'cancel' || current.cancel_requested ? 'cancelled' : 'paused')
        .input('cancel', sql.Bit, action === 'cancel' || current.cancel_requested)
        .input('lease', sql.NVarChar(128), action === 'acquire' ? run.lease_id : null)
        .input('until', sql.DateTime2, action === 'acquire' ? new Date(store.now.getTime()+120000) : null)
        .input('now', sql.DateTime2, store.now)
        .query(`UPDATE dbo.VolumeRuns SET status=@status,cancel_requested=@cancel,
          lease_id=@lease,lease_expires_at=@until,updated_at=@now WHERE run_key=@run`);
      return { entity_key: run.profile.run_key, status: action, event_ids: [] };
    }, { runId: run.profile.run_key });
}

export async function readRun(pool: sql.ConnectionPool, runKey: string): Promise<{ run: VolumeRun; committed: number[] }> {
  const result = await pool.request().input('run', sql.NVarChar(64), runKey)
    .input('prefix', sql.NVarChar(128), `volume:${runKey}:batch:`)
    .query(`SELECT * FROM dbo.VolumeRuns WHERE run_key=@run;
      SELECT result_json FROM dbo.CommandReceipts WHERE LEFT(idempotency_key,LEN(@prefix))=@prefix`);
  const sets = result.recordsets as sql.IRecordSet<unknown>[];
  if (sets[0].length !== 1) throw new Error('Volume run not initialized.');
  const committed = (sets[1] as unknown as { result_json: string }[]).map((row: { result_json: string }) =>
    (JSON.parse(row.result_json) as { batch_index: number }).batch_index);
  if (committed.some((index: number) => !Number.isInteger(index))) throw new Error('Run checkpoint receipt is malformed.');
  return { run: sets[0][0] as VolumeRun, committed: committed.sort((a: number,b: number) => a-b) };
}
