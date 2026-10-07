/** Bounded cardinality/provenance proof, not an unbounded row or payload dump. */
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {parseArgs} from 'node:util';
import {poolFor} from '../rayfin/functions/dist/src/storage.js';
import {canonical,key} from '../rayfin/functions/dist/src/domain.js';
const require=createRequire(new URL('../rayfin/functions/package.json',import.meta.url));
const sql=require('mssql');const{DefaultAzureCredential}=require('@azure/identity');
const{values}=parseArgs({options:{binding:{type:'string',default:'tools/binding.live.local.json'},
  run:{type:'string',default:'msflix-volume-test-1000-20261007'}}});
const b=JSON.parse(await readFile(values.binding,'utf8'));
const token=await new DefaultAzureCredential({tenantId:b.tenant_id}).getToken('https://database.windows.net/.default');
const pool=await poolFor(b,token.token);
try{
  const result=await pool.request().input('run',sql.NVarChar(64),key(values.run,'run key')).query(`
    SELECT 'Contents' AS entity,COUNT(*) AS count FROM dbo.Contents
    UNION ALL SELECT 'Customers',COUNT(*) FROM dbo.Customers
    UNION ALL SELECT 'Offers',COUNT(*) FROM dbo.Offers
    UNION ALL SELECT 'Rentals',COUNT(*) FROM dbo.Rentals
    UNION ALL SELECT 'Playbacks',COUNT(*) FROM dbo.Playbacks
    UNION ALL SELECT 'Outboxes',COUNT(*) FROM dbo.Outboxes;
    SELECT artwork_available,COUNT(*) AS count FROM dbo.Contents GROUP BY artwork_available;
    SELECT run_key,status,total_orders,total_events,committed_orders,committed_events,committed_batches,
      cancel_requested,requested_at,updated_at FROM dbo.VolumeRuns WHERE run_key=@run;
    SELECT event_type,COUNT(*) AS count FROM dbo.Outboxes WHERE run_id=@run GROUP BY event_type;
    SELECT COUNT(*) AS acknowledged_total,SUM(CASE WHEN run_id=@run THEN 1 ELSE 0 END) AS acknowledged_run
      FROM dbo.Outboxes WHERE published_at IS NOT NULL;
    SELECT JSON_VALUE(payload_json,'$.status') AS status,COUNT(*) AS count FROM dbo.Outboxes
      WHERE run_id=@run AND event_type='rental.updated' GROUP BY JSON_VALUE(payload_json,'$.status');
    SELECT JSON_VALUE(payload_json,'$.status') AS status,COUNT(*) AS count FROM dbo.Outboxes
      WHERE run_id=@run AND event_type='playback.updated' GROUP BY JSON_VALUE(payload_json,'$.status');
    SELECT COUNT(*) AS payload_failures FROM dbo.Outboxes WHERE payload<>payload_json OR ISJSON(payload_json)<>1;
    SELECT COUNT(*) AS duplicate_event_keys FROM (SELECT event_id FROM dbo.Outboxes GROUP BY event_id HAVING COUNT(*)>1) d;
  `);
  console.log(canonical({captured_at:new Date(),counts:result.recordsets[0],artwork:result.recordsets[1],
    run:result.recordsets[2],run_events:result.recordsets[3],acks:result.recordsets[4],
    rental_states:result.recordsets[5],playback_states:result.recordsets[6],
    integrity:result.recordsets[7],duplicates:result.recordsets[8]}));
}finally{await pool.close();}
