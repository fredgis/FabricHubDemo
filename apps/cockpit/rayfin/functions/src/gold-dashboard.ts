import type sql from 'mssql';
import type { AnalyticsBinding } from '../../data/schema.js';
import { assertGoldBinding, withGoldPool } from './gold-connection.js';
export { assertGoldBinding, connectGoldPool, goldPool, withGoldPool } from './gold-connection.js';

export type GoldDashboard = {
  source:{name:string;workspace_id:string;item_id:string;views:string[]};
  state:'ready'|'empty'|'unpublished';
  freshness:{queried_at:string;published_at:string|null;publication_run_id:string|null;order_lines:string|null};
  commercial:{currency:string;transaction_type:string;current_order_lines:string;booked_amount_minor:string;booked_amount_decimal:string}[];
  playback:{content_key:string;status:string;current_sessions:string;furthest_position_seconds:string}[];
  campaigns:{campaign_key:string;recorded_conversions:string}[];
  dimensions:{customers:string;content:string};
};
/** Catalog requests publication metadata, not dashboard aggregates. Ready means published; null is not zero activity. */
export type GoldCatalogDashboard=Pick<GoldDashboard,'source'|'freshness'>&{
  scope:'catalog';
  state:'ready'|'unpublished';
  commercial:null;playback:null;campaigns:null;dimensions:null;
};
export type GoldRows={commercial:GoldDashboard['commercial'];playback:GoldDashboard['playback'];
  campaigns:GoldDashboard['campaigns'];counts:{customers:string;content:string}[];
  publication:{run_id:string;completed_at:Date|string;order_lines:string}[]};
type GoldSource=Pick<AnalyticsBinding,'workspace_id'|'item_id'|'name'>;
function integer(value:unknown,label:string):string{
  const text=String(value);
  if(!/^\d+$/.test(text))throw new Error(`Gold ${label} is not an exact nonnegative integer.`);
  return text;
}
function publicationFreshness(publication:GoldRows['publication'][number]|undefined,now:Date):GoldDashboard['freshness']{
  const published=publication?new Date(publication.completed_at):null;
  if(published&&!Number.isFinite(published.getTime()))throw new Error('Gold publication timestamp is invalid.');
  return{queried_at:now.toISOString(),published_at:published?.toISOString()??null,
    publication_run_id:publication?.run_id??null,order_lines:publication?integer(publication.order_lines,'published order lines'):null};
}
export function catalogDashboardFromRows(source:GoldSource,publication:GoldRows['publication'],now:Date):GoldCatalogDashboard{
  return{source:{...source,views:['gold.publication']},scope:'catalog',state:publication.length?'ready':'unpublished',
    freshness:publicationFreshness(publication[0],now),commercial:null,playback:null,campaigns:null,dimensions:null};
}
export function dashboardFromRows(source:GoldSource,rows:GoldRows,now:Date):GoldDashboard{
  const publication=rows.publication[0];
  const freshness=publicationFreshness(publication,now);
  const commercial=rows.commercial.map(row=>({...row,current_order_lines:integer(row.current_order_lines,'order lines'),
    booked_amount_minor:integer(row.booked_amount_minor,'minor amount')}));
  const playback=rows.playback.map(row=>({...row,current_sessions:integer(row.current_sessions,'sessions'),
    furthest_position_seconds:integer(row.furthest_position_seconds,'playback position')}));
  const campaigns=rows.campaigns.map(row=>({...row,recorded_conversions:integer(row.recorded_conversions,'conversions')}));
  return {source:{...source,views:['gold.commercial_activity','gold.playback_activity','gold.campaign_activity']},
    state:!publication?'unpublished':commercial.length||playback.length||campaigns.length?'ready':'empty',
    freshness,
    commercial:publication?commercial:[],playback:publication?playback:[],campaigns:publication?campaigns:[],
    dimensions:{customers:integer(rows.counts[0]?.customers??'0','customers'),content:integer(rows.counts[0]?.content??'0','content')}};
}
export const GOLD_PUBLICATION_QUERY=`
      SELECT TOP (1) run_id,completed_at,CONVERT(varchar(40),order_lines) AS order_lines
      FROM gold.publication ORDER BY completed_at DESC,run_id;`;
export const GOLD_DASHBOARD_QUERY=`
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
        CONVERT(varchar(40),(SELECT COUNT_BIG(*) FROM gold.dim_content)) AS content;${GOLD_PUBLICATION_QUERY}`;
export function dashboardFromRecordsets(binding:AnalyticsBinding,sets:sql.IRecordSet<unknown>[]):GoldDashboard{
  return dashboardFromRows({name:binding.name,workspace_id:binding.workspace_id,item_id:binding.item_id},{
      commercial:sets[0] as unknown as GoldRows['commercial'],playback:sets[1] as unknown as GoldRows['playback'],
      campaigns:sets[2] as unknown as GoldRows['campaigns'],counts:sets[3] as unknown as GoldRows['counts'],
      publication:sets[4] as unknown as GoldRows['publication']},new Date());
}
export function catalogDashboardFromRecordsets(binding:AnalyticsBinding,sets:sql.IRecordSet<unknown>[]):GoldCatalogDashboard{
  return catalogDashboardFromRows({name:binding.name,workspace_id:binding.workspace_id,item_id:binding.item_id},
    sets[0] as unknown as GoldRows['publication'],new Date());
}
export async function readGoldDashboard(binding:AnalyticsBinding,token:string):Promise<GoldDashboard>{
  assertGoldBinding(binding);
  try{
    return await withGoldPool(binding,token,async pool=>{
      const result=await pool.request().query(GOLD_DASHBOARD_QUERY);
      return dashboardFromRecordsets(binding,result.recordsets as sql.IRecordSet<unknown>[]);
    });
  }catch(error){
    const failure=error as{code?:string;number?:number;originalError?:{info?:{number?:number}}};
    const code=failure.code??'GOLD_QUERY_FAILED';
    const number=failure.number??failure.originalError?.info?.number;
    const detail=number===208?'Required Gold curated view/table is missing.':
      number===229?'App-owner SELECT permission on Gold is missing.':`Gold SQL query failed${number?` (${number})`:''}.`;
    throw new Error(`MSFlixGold curated dashboard unavailable (${code}). ${detail} Verify Gold views/publication and app-owner SQL access. No operational fallback.`);
  }
}
