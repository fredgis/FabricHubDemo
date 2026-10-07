import sql from 'mssql';
import type { AnalyticsBinding } from '../../data/schema.js';

export type GoldDashboard = {
  source:{name:string;workspace_id:string;item_id:string;views:string[]};
  state:'ready'|'empty'|'unpublished';
  freshness:{queried_at:string;published_at:string|null;publication_run_id:string|null;order_lines:string|null};
  commercial:{currency:string;transaction_type:string;current_order_lines:string;booked_amount_minor:string;booked_amount_decimal:string}[];
  playback:{content_key:string;status:string;current_sessions:string;furthest_position_seconds:string}[];
  campaigns:{campaign_key:string;recorded_conversions:string}[];
  dimensions:{customers:string;content:string};
};
export type GoldRows={commercial:GoldDashboard['commercial'];playback:GoldDashboard['playback'];
  campaigns:GoldDashboard['campaigns'];counts:{customers:string;content:string}[];
  publication:{run_id:string;completed_at:Date|string;order_lines:string}[]};
export function dashboardFromRows(source:{workspace_id:string;item_id:string;name:string},rows:GoldRows,now:Date):GoldDashboard{
  const publication=rows.publication[0];
  const integer=(value:unknown,label:string)=>{
    const text=String(value);
    if(!/^\d+$/.test(text))throw new Error(`Gold ${label} is not an exact nonnegative integer.`);
    return text;
  };
  const published=publication?new Date(publication.completed_at):null;
  if(published && !Number.isFinite(published.getTime()))throw new Error('Gold publication timestamp is invalid.');
  const commercial=rows.commercial.map(row=>({...row,current_order_lines:integer(row.current_order_lines,'order lines'),
    booked_amount_minor:integer(row.booked_amount_minor,'minor amount')}));
  const playback=rows.playback.map(row=>({...row,current_sessions:integer(row.current_sessions,'sessions'),
    furthest_position_seconds:integer(row.furthest_position_seconds,'playback position')}));
  const campaigns=rows.campaigns.map(row=>({...row,recorded_conversions:integer(row.recorded_conversions,'conversions')}));
  return {source:{...source,views:['gold.commercial_activity','gold.playback_activity','gold.campaign_activity']},
    state:!publication?'unpublished':commercial.length||playback.length||campaigns.length?'ready':'empty',
    freshness:{queried_at:now.toISOString(),published_at:published?.toISOString()??null,
      publication_run_id:publication?.run_id??null,order_lines:publication?integer(publication.order_lines,'published order lines'):null},
    commercial:publication?commercial:[],playback:publication?playback:[],campaigns:publication?campaigns:[],
    dimensions:{customers:integer(rows.counts[0]?.customers??'0','customers'),content:integer(rows.counts[0]?.content??'0','content')}};
}
export async function readGoldDashboard(binding:AnalyticsBinding,token:string):Promise<GoldDashboard>{
  if(!binding.verified || binding.binding_key!=='business-gold' || binding.name!=='MSFlixGold' ||
      !binding.sql_server.endsWith('.datawarehouse.fabric.microsoft.com') ||
      binding.sql_database!==binding.item_id || !/^[a-f0-9-]{36}$/i.test(binding.item_id))
    throw new Error('Gold Warehouse binding is not verified. Operational SQL will not substitute for Gold.');
  const pool=new sql.ConnectionPool({server:binding.sql_server,database:binding.sql_database,
    options:{encrypt:true,trustServerCertificate:false},
    authentication:{type:'azure-active-directory-access-token',options:{token}},
    connectionTimeout:15000,requestTimeout:30000,pool:{min:0,max:1,idleTimeoutMillis:1000}});
  try{
    for(let attempt=0;;attempt++){
      try{await pool.connect();break;}
      catch(error){if(attempt>=2||!['ETIMEOUT','ESOCKET','ECONNRESET'].includes((error as {code?:string}).code??''))throw error;
        await new Promise(resolve=>setTimeout(resolve,250*2**attempt));}
    }
    const result=await pool.request().query(`
      SELECT currency,transaction_type,CONVERT(varchar(40),current_order_lines) AS current_order_lines,
        CONVERT(varchar(40),booked_amount_minor) AS booked_amount_minor,
        CONVERT(varchar(64),booked_amount_decimal) AS booked_amount_decimal
      FROM gold.commercial_activity ORDER BY currency,transaction_type;
      SELECT content_key,status,CONVERT(varchar(40),current_sessions) AS current_sessions,
        CONVERT(varchar(40),furthest_position_seconds) AS furthest_position_seconds
      FROM gold.playback_activity ORDER BY content_key,status;
      SELECT campaign_key,CONVERT(varchar(40),recorded_conversions) AS recorded_conversions
      FROM gold.campaign_activity ORDER BY campaign_key;
      SELECT CONVERT(varchar(40),(SELECT COUNT_BIG(*) FROM gold.dim_customer)) AS customers,
        CONVERT(varchar(40),(SELECT COUNT_BIG(*) FROM gold.dim_content)) AS content;
      SELECT TOP (1) run_id,completed_at,CONVERT(varchar(40),order_lines) AS order_lines
      FROM gold.publication ORDER BY completed_at DESC,run_id;`);
    const sets=result.recordsets as sql.IRecordSet<unknown>[];
    return dashboardFromRows({name:binding.name,workspace_id:binding.workspace_id,item_id:binding.item_id},{
      commercial:sets[0] as unknown as GoldRows['commercial'],playback:sets[1] as unknown as GoldRows['playback'],
      campaigns:sets[2] as unknown as GoldRows['campaigns'],counts:sets[3] as unknown as GoldRows['counts'],
      publication:sets[4] as unknown as GoldRows['publication']},new Date());
  }catch(error){
    const failure=error as{code?:string;number?:number;originalError?:{info?:{number?:number}}};
    const code=failure.code??'GOLD_QUERY_FAILED';
    const number=failure.number??failure.originalError?.info?.number;
    const detail=number===208?'Required Gold curated view/table is missing.':
      number===229?'App-owner SELECT permission on Gold is missing.':`Gold SQL query failed${number?` (${number})`:''}.`;
    throw new Error(`MSFlixGold curated dashboard unavailable (${code}). ${detail} Verify Gold views/publication and app-owner SQL access. No operational fallback.`);
  }finally{await pool.close();}
}
