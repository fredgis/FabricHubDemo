import{useCallback,useEffect,useState}from'react';
import{ArrowsClockwise}from'@phosphor-icons/react';
import{getRayfinClient}from'@/services/rayfinClient';
import{dateLabel,safeError}from'@/services/business';
import type{GoldDashboard}from'../../rayfin/functions/src/gold-dashboard';

function exactMoney(value:string,currency:string):string{
  const minor=BigInt(value);
  const format=new Intl.NumberFormat('en',{style:'currency',currency});
  const digits=format.resolvedOptions().maximumFractionDigits??2;
  const divisor=10n**BigInt(digits);
  const fraction=(minor%divisor).toString().padStart(digits,'0');
  return format.formatToParts(minor/divisor).map(part=>part.type==='fraction'?fraction:part.value).join('');
}
function sum(rows:{current_order_lines?:string;current_sessions?:string}[],field:'current_order_lines'|'current_sessions'):string{
  return rows.reduce((total,row)=>total+BigInt(row[field]??'0'),0n).toLocaleString('en');
}
export function GoldBusinessDashboard({refreshKey=0}:{refreshKey?:number}){
  const[data,setData]=useState<GoldDashboard>();
  const[error,setError]=useState('');
  const[loading,setLoading]=useState(true);
  const load=useCallback(async()=>{
    setLoading(true);setError('');setData(undefined);
    try{setData(await getRayfinClient().functions.businessDashboard.invoke());}
    catch(err){setError(safeError(err));}finally{setLoading(false);}
  },[]);
  useEffect(()=>{void load();},[load,refreshKey]);
  const totals=new Map<string,bigint>();
  for(const row of data?.commercial??[])totals.set(row.currency,(totals.get(row.currency)??0n)+BigInt(row.booked_amount_minor));
  return <section className="gold-dashboard" aria-label="Gold Warehouse business dashboard" aria-busy={loading}>
    <div className="gold-source"><div><h2>Business performance</h2><p>Source: MSFlixGold Warehouse. Curated commercial, playback and campaign views.</p>
      <small>Operational SQL is not used as a fallback.</small></div>
      <button onClick={()=>void load()} disabled={loading}><ArrowsClockwise aria-hidden="true"/>{loading?'Reading Gold…':'Refresh Gold'}</button></div>
    {loading&&<p role="status" className="muted">Reading actual Gold curated views…</p>}
    {error&&<div className="error-state" role="alert"><h3>Gold dashboard unavailable</h3><p>{error}</p>
      <p>No consolidated KPI values are displayed until the Gold query succeeds.</p></div>}
    {data&&<><p className="gold-freshness">Query: {dateLabel(data.freshness.queried_at)}
      <br/>Gold publication: {data.freshness.published_at?dateLabel(data.freshness.published_at):'No completed publication recorded'}
      {data.freshness.publication_run_id&&<small>Publication run: {data.freshness.publication_run_id}</small>}</p>
      {data.state==='unpublished'?<div className="empty-state"><h3>Gold is not published yet</h3>
        <p>The Warehouse endpoint responded, but no completed Gold publication exists. Operational sales are not substituted.</p></div>
      :data.state==='empty'?<div className="empty-state"><h3>No curated business activity</h3>
        <p>The last completed Gold publication contains no commercial, playback or campaign facts.</p></div>
      :<><div className="metrics" aria-label="Curated Gold business metrics">
        <div><span>Recorded sales</span><strong>{[...totals].map(([currency,total])=><span key={currency}>{exactMoney(total.toString(),currency)}</span>)}</strong>
          <small>Gold booked commercial amounts, by currency. No bank payment or margin.</small></div>
        <div><span>Order lines</span><strong>{sum(data.commercial,'current_order_lines')}</strong><small>gold.commercial_activity</small></div>
        <div><span>Playback sessions</span><strong>{sum(data.playback,'current_sessions')}</strong><small>gold.playback_activity</small></div>
        <div><span>Curated customers</span><strong>{BigInt(data.dimensions.customers).toLocaleString('en')}</strong><small>Gold customer dimension</small></div>
      </div><div className="gold-detail-grid"><section><h3>Commercial mix</h3><div className="table-scroll"><table>
        <thead><tr><th scope="col">Category</th><th scope="col">Order lines</th><th scope="col">Booked amount</th></tr></thead>
        <tbody>{data.commercial.map(row=><tr key={`${row.currency}:${row.transaction_type}`}><td>{row.transaction_type} / {row.currency}</td>
          <td>{row.current_order_lines}</td><td>{exactMoney(row.booked_amount_minor,row.currency)}</td></tr>)}</tbody></table></div></section>
        <section><h3>Recorded campaign conversions</h3>{data.campaigns.length?<ul>{data.campaigns.map(row=>
          <li key={row.campaign_key}>{row.campaign_key}: {row.recorded_conversions}</li>)}</ul>
          :<p className="muted">No campaign conversions exist in the curated Gold view.</p>}</section></div></>}
      <p className="gold-contract"><small>Warehouse item: {data.source.item_id}<br/>Views: {data.source.views.join(', ')}</small></p></>}
  </section>;
}
