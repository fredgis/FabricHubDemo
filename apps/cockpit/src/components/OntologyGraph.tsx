import{useEffect,useState,useCallback}from'react';
import{getRayfinClient}from'@/services/rayfinClient';
import{dateLabel,safeError}from'@/services/business';
import type{OntologyGraph as Result}from'../../rayfin/functions/src/ontology-graph';
export function OntologyGraph(){
  const[data,setData]=useState<Result>();const[error,setError]=useState('');const[loading,setLoading]=useState(true);
  const load=useCallback(async()=>{
    setLoading(true);setData(undefined);setError('');
    try{setData(await getRayfinClient().functions.businessGraph.invoke());}catch(err){setError(safeError(err));}
    finally{setLoading(false);}
  },[]);
  useEffect(()=>{void load();},[load]);
  return<section aria-label="Actual Ontology v2 graph" aria-busy={loading}>
    <h2>MSFlix business ontology</h2><p className="muted">Generation-two ontology and its actual GraphModel query. No operational graph substitution.</p>
    <button disabled={loading} onClick={()=>void load()}>{loading?'Reading graph…':'Refresh graph'}</button>
    {error&&<div className="error-state" role="alert"><h3>Ontology read unavailable</h3><p>{error}</p></div>}
    {data&&<><p className="gold-freshness">Source: Ontology {data.source.ontology_id}<br/>GraphModel {data.source.graph_model_id}<br/>Read {dateLabel(data.queried_at)}</p>
      {data.state!=='ready'?<div className="empty-state"><h3>{data.state==='binding-mismatch'?'Gold ontology binding pending':data.state==='pending'?'Graph initial load pending':'No graph instances'}</h3><p>{data.message}</p></div>
        :<div className="business-graph">{['customer','rental','offer','content'].map(type=><section key={type}>
          <h3>{type}</h3>{data.nodes.filter(node=>node.type===type).map(node=><article key={node.key}><strong>{node.label}</strong><small>{node.key}</small></article>)}
        </section>)}</div>}
      {data.state==='ready'&&<details><summary>Actual relationships ({data.edges.length}, query limit {data.limit})</summary><ul>
        {data.edges.map(edge=><li key={`${edge.from}:${edge.to}`}>{edge.from} → {edge.type} → {edge.to}</li>)}</ul></details>}
    </>}
  </section>;
}
