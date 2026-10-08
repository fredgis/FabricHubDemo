import sql from 'mssql';
import type{AnalyticsBinding}from'../../data/schema.js';
import{connectGoldPool,dashboardFromRecordsets,GOLD_DASHBOARD_QUERY,goldPool,type GoldDashboard}from'./gold-dashboard.js';
export type GoldView='all'|'overview'|'catalog'|'audiences'|'demo';
export function goldView(value:string):GoldView{
  if(value==='all'||value==='overview'||value==='catalog'||value==='audiences'||value==='demo')return value;
  throw new Error('Unsupported Gold business page.');
}
export type GoldPages={
  dashboard:GoldDashboard;
  catalog:Record<string,string|null>[];
  customers:Record<string,string|null>[];
  offers:Record<string,string|null>[];
  orders:Record<string,string|null>[];
  sessions:Record<string,string|null>[];
  campaigns:Record<string,string|null>[];
  window:{orders:number;sessions:number;references:number};
};
/** Business references and read-only activity are Gold only. No app-SQL fallback. */
export async function readGoldPages(binding:AnalyticsBinding,token:string,requestedView:GoldView='all'):Promise<GoldPages>{
  const view=goldView(requestedView);
  const activity=view==='overview'?6:1000;
  const window={orders:activity,sessions:activity,references:10000};
  const pool=goldPool(binding,token);
  try{
    await connectGoldPool(pool);
    const result=await pool.request().input('references',sql.Int,10001).input('activity',sql.Int,activity)
      .input('view',sql.VarChar(16),view).query(GOLD_DASHBOARD_QUERY+`
      SELECT TOP (@references) content_key,title,CONVERT(varchar(10),release_date,23) AS release_date,
        CONVERT(varchar(40),duration_seconds) AS duration_seconds,genre,image_url,source_url,license,attribution,distributor_key
      FROM gold.dim_content
      WHERE @view IN ('all','catalog','demo') OR (@view='overview' AND (
        content_key='MSF-FILM-BUNNY'
        OR content_key IN (SELECT TOP (@activity) content_key FROM gold.fact_order_line ORDER BY created_at DESC,order_id)
        OR content_key IN (SELECT TOP (@activity) content_key FROM gold.fact_playback_session ORDER BY occurred_at DESC,session_id)))
      ORDER BY content_key;
      SELECT TOP (@references) customer_key,name,territory,source_customer_id FROM gold.dim_customer
      WHERE @view IN ('all','audiences','demo') OR (@view='overview' AND customer_key IN
        (SELECT TOP (@activity) customer_key FROM gold.fact_order_line ORDER BY created_at DESC,order_id))
      ORDER BY customer_key;
      SELECT TOP (@references) offer_key,content_key,territory,currency,transaction_type,
        CONVERT(varchar(40),price_minor) AS price_minor,CONVERT(varchar(40),start_window_hours) AS start_window_hours,
        CONVERT(varchar(40),play_window_hours) AS play_window_hours FROM gold.dim_offer
      WHERE @view IN ('all','catalog','demo') OR (@view='overview' AND offer_key IN
        (SELECT TOP (@activity) offer_key FROM gold.fact_order_line ORDER BY created_at DESC,order_id))
      ORDER BY offer_key;
      SELECT TOP (@activity) order_id,customer_key,offer_key,content_key,status,currency,transaction_type,
        CONVERT(varchar(40),amount_minor) AS amount_minor,CONVERT(varchar(33),created_at,127)+'Z' AS created_at,
        CONVERT(varchar(33),start_deadline,127)+'Z' AS start_deadline,
        CONVERT(varchar(33),first_play_at,127)+'Z' AS first_play_at,
        CONVERT(varchar(33),expires_at,127)+'Z' AS expires_at,CONVERT(varchar(40),source_sequence) AS source_sequence
      FROM gold.fact_order_line WHERE @view<>'catalog' ORDER BY created_at DESC,order_id;
      SELECT TOP (@activity) session_id,order_id,content_key,customer_key,status,
        CONVERT(varchar(40),position_seconds) AS position_seconds,CONVERT(varchar(33),occurred_at,127)+'Z' AS occurred_at
      FROM gold.fact_playback_session WHERE @view IN ('all','overview','demo') ORDER BY occurred_at DESC,session_id;
      SELECT TOP (@references) campaign_key,name,territory,channel FROM gold.dim_campaign
      WHERE @view IN ('all','audiences') ORDER BY campaign_key;`);
    const allSets=result.recordsets as sql.IRecordSet<unknown>[];
    const dashboard=dashboardFromRecordsets(binding,allSets);
    if(dashboard.state==='unpublished')return{dashboard,catalog:[],customers:[],offers:[],orders:[],sessions:[],campaigns:[],window};
    const sets=allSets.slice(5) as sql.IRecordSet<Record<string,string|null>>[];
    if([sets[0],sets[1],sets[2],sets[5]].some(rows=>rows.length>10000))
      throw new Error('Gold reference collection exceeds safe read boundary; no partial totals are presented.');
    return{dashboard,catalog:sets[0],customers:sets[1],offers:sets[2],orders:sets[3],sessions:sets[4],campaigns:sets[5],
      window};
  }catch(error){throw new Error(`Gold business views unavailable (${(error as{code?:string}).code??'READ_ERROR'}). No operational fallback.`);}
  finally{await pool.close();}
}
