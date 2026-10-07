/** Read-only, credential-redacted SQL evidence for this exact app binding. */
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { parseArgs } from 'node:util';
import { poolFor } from '../rayfin/functions/dist/src/storage.js';
const require = createRequire(new URL('../rayfin/functions/package.json', import.meta.url));
const { DefaultAzureCredential } = require('@azure/identity');
const { values } = parseArgs({ options: { binding: { type:'string', default:'tools/binding.live.local.json' } } });
const sql=require('mssql');
const binding = JSON.parse(await readFile(values.binding, 'utf8'));
const token = await new DefaultAzureCredential({ tenantId:binding.tenant_id }).getToken('https://database.windows.net/.default');
const pool = await poolFor(binding, token.token);
try {
  const result = await pool.request().input('detailLimit',sql.Int,10).query(`
    SELECT 'Contents' AS entity,COUNT(*) AS count FROM dbo.Contents
    UNION ALL SELECT 'Customers',COUNT(*) FROM dbo.Customers
    UNION ALL SELECT 'Offers',COUNT(*) FROM dbo.Offers
    UNION ALL SELECT 'Campaigns',COUNT(*) FROM dbo.Campaigns
    UNION ALL SELECT 'Rentals',COUNT(*) FROM dbo.Rentals
    UNION ALL SELECT 'Playbacks',COUNT(*) FROM dbo.Playbacks
    UNION ALL SELECT 'Outboxes',COUNT(*) FROM dbo.Outboxes
    UNION ALL SELECT 'CommandReceipts',COUNT(*) FROM dbo.CommandReceipts;
    SELECT TOP (@detailLimit) order_id,offer_key,status,amount_minor,currency,start_deadline,first_play_at,expires_at FROM dbo.Rentals ORDER BY created_at DESC;
    SELECT TOP (@detailLimit) session_id,order_id,position_seconds,status FROM dbo.Playbacks ORDER BY session_id;
    SELECT event_type,COUNT(*) AS count FROM dbo.Outboxes GROUP BY event_type ORDER BY event_type;
    SELECT COUNT(*) AS canonical_failures FROM dbo.Outboxes WHERE payload<>payload_json OR ISJSON(payload_json)<>1;
    SELECT COUNT(*) AS duplicate_events FROM (SELECT event_id FROM dbo.Outboxes GROUP BY event_id HAVING COUNT(*)>1) d;
    SELECT COUNT(*) AS acknowledged FROM dbo.Outboxes WHERE published_at IS NOT NULL;
    SELECT c.name,TYPE_NAME(c.user_type_id) AS sql_type,c.max_length,c.is_nullable
      FROM sys.columns c WHERE c.object_id=OBJECT_ID('dbo.Outboxes') ORDER BY c.column_id;
  `);
  console.log(JSON.stringify({ verified_binding: true, captured_at: new Date().toISOString(),
    counts:result.recordsets[0],detail_limit:10,orders:result.recordsets[1],playback:result.recordsets[2],
    event_types:result.recordsets[3], canonical:result.recordsets[4], duplicates:result.recordsets[5],
    acknowledged:result.recordsets[6], outbox_columns:result.recordsets[7] }));
} catch (error) {
  console.error(JSON.stringify({ verified: false, code: error?.code ?? 'SQL_VERIFICATION_FAILED' }));
  process.exitCode = 1;
} finally { await pool.close(); }
