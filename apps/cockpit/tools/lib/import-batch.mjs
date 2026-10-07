/** Set-based trusted source import. Identifiers come only from closed importer definitions. */
import { createRequire } from 'node:module';
import { emitMany, publicState } from '../../rayfin/functions/dist/src/storage.js';
import{contentEventState,releaseDateOnly}from'./content-event.mjs';
const require=createRequire(new URL('../../rayfin/functions/package.json',import.meta.url));
const sql=require('mssql');
const tables=new Set(['Content','Customer','Offer','Campaign','CampaignMember','IntegrationLink']);
export async function upsertChunk(store,table,definition,records,lengths) {
  if(!tables.has(table) || records.length<1 || records.length>1000)throw new Error('Invalid bounded import table/chunk.');
  if(table==='Content')for(const row of records)releaseDateOnly(row.release_date);
  const dates=new Set(['release_date','start_date','end_date']);
  const numbers=new Set(['duration_seconds','price_minor','start_window_hours','play_window_hours']);
  const fields=definition.fields;
  if(fields.some(field=>!/^[a-z_]+$/.test(field)))throw new Error('Invalid closed import field.');
  const type=field=>{
    if(dates.has(field))return 'datetime2';
    if(numbers.has(field))return 'int';
    if(field==='artwork_available')return 'bit';
    if(!Number.isInteger(lengths[field]) || lengths[field]<1 || lengths[field]>4000)throw new Error('Invalid closed text length.');
    return `nvarchar(${lengths[field]})`;
  };
  const comparison=(alias,field)=>
    `${alias}.[${field}]${type(field).startsWith('nvarchar')?' COLLATE Latin1_General_100_BIN2':''}`;
  const differs=`EXISTS (SELECT ${fields.map(field=>comparison('p',field)).join(',')}
    EXCEPT SELECT ${fields.map(field=>comparison('s',field)).join(',')})`;
  const natural=definition.key;
  if(!fields.includes(natural))throw new Error('Natural key is missing from import fields.');
  const physical=`dbo.[${table}s]`;
  const rows=records.map(row=>Object.fromEntries(fields.map(field=>[field,row[field]??null])));
  const query=`
    SET NOCOUNT ON;
    DECLARE @Source TABLE (${fields.map(field=>`[${field}] ${type(field)}`).join(',')});
    INSERT @Source SELECT ${fields.map(field=>`[${field}]`).join(',')} FROM OPENJSON(@rows)
      WITH (${fields.map(field=>`[${field}] ${type(field)} '$.${field}'`).join(',')});
    ${table==='Offer'?`IF EXISTS (
      SELECT 1 FROM ${physical} p WITH (UPDLOCK,HOLDLOCK) JOIN @Source s ON p.[${natural}]=s.[${natural}]
      WHERE ${differs} AND EXISTS (SELECT 1 FROM dbo.Rentals r WHERE r.offer_key=p.offer_key))
      THROW 50005,'An offer with transactions is immutable. Use a new offer key.',1;`:''}
    DECLARE @Changed TABLE (natural_key ${type(natural)} PRIMARY KEY);
    UPDATE p SET ${fields.filter(field=>field!==natural).map(field=>`[${field}]=s.[${field}]`).join(',')}
      OUTPUT INSERTED.[${natural}] INTO @Changed
      FROM ${physical} p WITH (UPDLOCK,HOLDLOCK) JOIN @Source s ON p.[${natural}]=s.[${natural}]
      WHERE ${differs};
    INSERT ${physical} (id,${fields.map(field=>`[${field}]`).join(',')})
      OUTPUT INSERTED.[${natural}] INTO @Changed
      SELECT NEWID(),${fields.map(field=>`s.[${field}]`).join(',')} FROM @Source s
      WHERE NOT EXISTS (SELECT 1 FROM ${physical} p WITH (UPDLOCK,HOLDLOCK) WHERE p.[${natural}]=s.[${natural}]);
    SELECT ${fields.map(field=>`p.[${field}]`).join(',')} FROM ${physical} p
      JOIN @Changed c ON c.natural_key=p.[${natural}] ORDER BY p.[${natural}];
  `;
  const result=await new sql.Request(store.tx).input('rows',sql.NVarChar(sql.MAX),JSON.stringify(rows)).query(query);
  if(definition.event && result.recordset.length)
    await emitMany(store,result.recordset.map(row=>({event_type:definition.event,
      entity_key:row[natural],payload:definition.event==='content.upserted'?contentEventState(row):publicState(row)})));
  return result.recordset.length;
}
