/**
 * Adapter for the parent-owned Event Hubs producer/control worker.
 * Uses an already authenticated mssql ConnectionPool. No Kafka success is
 * reported here: the producer calls acknowledge only after a broker ACK.
 */
import { createRequire } from 'node:module';
const require = createRequire(new URL('../rayfin/functions/package.json', import.meta.url));
const sql = require('mssql');

export async function pendingEvents(pool, limit = 100) {
  if (!Number.isInteger(limit) || limit < 1 || limit > 100) throw new Error('Limit must be 1-100.');
  const result = await pool.request().input('limit', sql.Int, limit).query(`
    SELECT TOP (@limit) event_id,event_type,schema_version,entity_key,source_sequence,
      occurred_at,produced_at,run_id,correlation_id,payload_json
    FROM dbo.Outboxes WHERE published_at IS NULL ORDER BY source_sequence`);
  return result.recordset.map(row => ({ ...row,
    occurred_at: new Date(row.occurred_at).toISOString(),
    produced_at: new Date(row.produced_at).toISOString(),
    payload: JSON.parse(row.payload_json),
  }));
}

export async function acknowledge(pool, eventId) {
  const result = await pool.request().input('id', sql.NVarChar(128), eventId).query(`
    UPDATE dbo.Outboxes SET published_at=SYSUTCDATETIME()
    WHERE event_id=@id AND published_at IS NULL`);
  return result.rowsAffected[0];
}

export async function claimControl(pool) {
  const result = await pool.request().query(`
    ;WITH next_command AS (
      SELECT TOP (1) * FROM dbo.ControlCommands WITH (UPDLOCK,READPAST,ROWLOCK)
      WHERE status='requested' ORDER BY requested_at,id
    )
    UPDATE next_command SET status='running'
    OUTPUT INSERTED.id,INSERTED.type,INSERTED.parameters;`);
  return result.recordset[0] ?? null;
}

export async function finishControl(pool, id, error = null) {
  const safe = error ? String(error).replace(/Bearer\s+\S+/gi, 'Bearer [redacted]')
    .replace(/eyJ[\w-]+\.[\w-]+\.[\w-]+/g, '[redacted]')
    .replace(/(password|secret|token|sig)=([^;&\s]+)/gi, '$1=[redacted]').slice(0, 1000) : null;
  const result = await pool.request().input('id', sql.UniqueIdentifier, id)
    .input('status', sql.NVarChar(24), error ? 'failed' : 'completed')
    .input('error', sql.NVarChar(1000), safe)
    .query(`UPDATE dbo.ControlCommands SET status=@status,error=@error,completed_at=SYSUTCDATETIME()
      WHERE id=@id AND status='running'`);
  if (result.rowsAffected[0] !== 1) throw new Error('Control command is not owned in a running state.');
}
