import type{Content}from'../../rayfin/data/schema';
import{getRayfinClient}from'./rayfinClient';
import type{Snapshot}from'./business';
import type{GoldPages}from'../../rayfin/functions/src/gold-pages';
export function goldSnapshot(pages:GoldPages):Snapshot{
  const text=(value:string|null|undefined)=>value??'';
  const integer=(value:string|null|undefined)=>{
    const number=Number(value);
    if(value==null||!Number.isSafeInteger(number)||number<0)throw new Error('Gold numeric field is not an exact safe integer.');
    return number;
  };
  const date=(value:string|null|undefined)=>value?new Date(value):undefined;
  return{
    content:pages.catalog.map(row=>({id:text(row.content_key),content_key:text(row.content_key),title:text(row.title),
      release_date:date(row.release_date)??new Date('invalid'),duration_seconds:integer(row.duration_seconds),
      genre:text(row.genre),image_url:text(row.image_url),source_url:text(row.source_url),license:text(row.license),
      attribution:text(row.attribution),metadata_license:text(row.license),metadata_date_precision:'year-display-only',
      artwork_available:row.image_url!==null&&row.image_url!=='/catalog-unavailable.svg'} as Content)),
    customers:pages.customers.map(row=>({id:text(row.customer_key),customer_key:text(row.customer_key),name:text(row.name),territory:text(row.territory)})),
    offers:pages.offers.map(row=>({id:text(row.offer_key),offer_key:text(row.offer_key),content_key:text(row.content_key),
      territory:text(row.territory),currency:text(row.currency),transaction_type:text(row.transaction_type),
      price_minor:integer(row.price_minor),start_window_hours:integer(row.start_window_hours),play_window_hours:integer(row.play_window_hours)})),
    rentals:pages.orders.map(row=>({id:text(row.order_id),order_id:text(row.order_id),customer_key:text(row.customer_key),
      offer_key:text(row.offer_key),status:text(row.status),amount_minor:integer(row.amount_minor),currency:text(row.currency),
      created_at:date(row.created_at)??new Date('invalid'),start_deadline:date(row.start_deadline),first_play_at:date(row.first_play_at),expires_at:date(row.expires_at)})),
    playback:pages.sessions.map(row=>({id:text(row.session_id),session_id:text(row.session_id),order_id:text(row.order_id),
      customer_key:text(row.customer_key),content_key:text(row.content_key),position_seconds:integer(row.position_seconds),status:text(row.status)})),
    campaigns:pages.campaigns.map(row=>({id:text(row.campaign_key),campaign_key:text(row.campaign_key),name:text(row.name),
      type:text(row.channel),status:'Gold reference'})),members:[],outbox:[],commands:[],links:[],
  };
}
export async function loadGoldViews():Promise<{pages:GoldPages;snapshot:Snapshot}>{
  const pages=await getRayfinClient().functions.businessViews.invoke();
  return{pages,snapshot:goldSnapshot(pages)};
}
