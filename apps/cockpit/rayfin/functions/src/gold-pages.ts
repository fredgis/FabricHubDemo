import sql from 'mssql';
import type{AnalyticsBinding}from'../../data/schema.js';
import{readGoldDashboard,type GoldDashboard}from'./gold-dashboard.js';
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
export async function readGoldPages(binding:AnalyticsBinding,token:string):Promise<GoldPages>{
  const dashboard=await readGoldDashboard(binding,token);
  if(dashboard.state==='unpublished')return{dashboard,catalog:[],customers:[],offers:[],orders:[],sessions:[],campaigns:[],
    window:{orders:1000,sessions:1000,references:10000}};
  const pool=new sql.ConnectionPool({server:binding.sql_server,database:binding.sql_database,
    options:{encrypt:true,trustServerCertificate:false},authentication:{type:'azure-active-directory-access-token',options:{token}},
    connectionTimeout:15000,requestTimeout:30000,pool:{min:0,max:1}});
  try{
    await pool.connect();
    const result=await pool.request().input('references',sql.Int,10001).input('activity',sql.Int,1000).query(`
      SELECT TOP (@references) content_key,title,CONVERT(varchar(10),release_date,23) AS release_date,
        CONVERT(varchar(40),duration_seconds) AS duration_seconds,genre,image_url,source_url,license,attribution,distributor_key
      FROM gold.dim_content ORDER BY content_key;
      SELECT TOP (@references) customer_key,name,territory,source_customer_id FROM gold.dim_customer ORDER BY customer_key;
      SELECT TOP (@references) offer_key,content_key,territory,currency,transaction_type,
        CONVERT(varchar(40),price_minor) AS price_minor,CONVERT(varchar(40),start_window_hours) AS start_window_hours,
        CONVERT(varchar(40),play_window_hours) AS play_window_hours FROM gold.dim_offer ORDER BY offer_key;
      SELECT TOP (@activity) order_id,customer_key,offer_key,content_key,status,currency,transaction_type,
        CONVERT(varchar(40),amount_minor) AS amount_minor,CONVERT(varchar(33),created_at,127)+'Z' AS created_at,
        CONVERT(varchar(33),start_deadline,127)+'Z' AS start_deadline,
        CONVERT(varchar(33),first_play_at,127)+'Z' AS first_play_at,
        CONVERT(varchar(33),expires_at,127)+'Z' AS expires_at,CONVERT(varchar(40),source_sequence) AS source_sequence
      FROM gold.fact_order_line ORDER BY created_at DESC,order_id;
      SELECT TOP (@activity) session_id,order_id,content_key,customer_key,status,
        CONVERT(varchar(40),position_seconds) AS position_seconds,CONVERT(varchar(33),occurred_at,127)+'Z' AS occurred_at
      FROM gold.fact_playback_session ORDER BY occurred_at DESC,session_id;
      SELECT TOP (@references) campaign_key,name,territory,channel FROM gold.dim_campaign ORDER BY campaign_key;`);
    const sets=result.recordsets as sql.IRecordSet<Record<string,string|null>>[];
    if([sets[0],sets[1],sets[2],sets[5]].some(rows=>rows.length>10000))
      throw new Error('Gold reference collection exceeds safe read boundary; no partial totals are presented.');
    return{dashboard,catalog:sets[0],customers:sets[1],offers:sets[2],orders:sets[3],sessions:sets[4],campaigns:sets[5],
      window:{orders:1000,sessions:1000,references:10000}};
  }catch(error){throw new Error(`Gold business views unavailable (${(error as{code?:string}).code??'READ_ERROR'}). No operational fallback.`);}
  finally{await pool.close();}
}
