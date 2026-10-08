import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowsClockwise, FilmSlate, ShoppingBag, Ticket, UserCircle } from '@phosphor-icons/react';
import {
  Background, BackgroundVariant, Controls, Handle, MiniMap, Position, ReactFlow,
  useNodesState, type NodeProps, type ReactFlowInstance, type Edge,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './OntologyGraph.css';
import { getRayfinClient } from '@/services/rayfinClient';
import { dateLabel, safeError } from '@/services/business';
import { createGraphScene, kindLabels, relationshipLabels, type BusinessNode, type GraphScene } from '@/domain/graph-scene';
import type { OntologyGraph as Result } from '../../rayfin/functions/src/ontology-graph';

const icons = { customer: UserCircle, rental: ShoppingBag, offer: Ticket, content: FilmSlate };
const BusinessNodeCard = memo(function BusinessNodeCard({ data, selected }: NodeProps<BusinessNode>) {
  const Icon = icons[data.kind as keyof typeof icons] ?? FilmSlate;
  return <div className={`ontology-node ontology-node-${data.kind}${selected ? ' is-selected' : ''}`}>
    <Handle type="target" position={Position.Left} isConnectable={false} />
    <span className="ontology-node-icon"><Icon size={24} aria-hidden="true" /></span>
    <div><span className="ontology-node-kind">{data.caption}</span>
      <strong title={data.title}>{data.title}</strong></div>
    <Handle type="source" position={Position.Right} isConnectable={false} />
  </div>;
});
const nodeTypes = { business: BusinessNodeCard };

export function GraphCanvas({ scene, onSelect }: { scene: GraphScene; onSelect: (id: string | undefined) => void }) {
  const [nodes, setNodes, onNodesChange] = useNodesState<BusinessNode>(scene.nodes);
  const flow = useRef<ReactFlowInstance<BusinessNode, Edge> | null>(null);
  useEffect(() => { setNodes(scene.nodes); }, [scene.nodes, setNodes]);
  const selectionChanged = useCallback(({ nodes: selected }: { nodes: BusinessNode[] }) => {
    onSelect(selected[0]?.id);
  }, [onSelect]);
  return <div className="ontology-canvas" aria-label="Interactive customer, order, offer and film graph">
    <ReactFlow<BusinessNode, Edge>
      nodes={nodes} edges={scene.edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange}
      onSelectionChange={selectionChanged} onPaneClick={() => onSelect(undefined)}
      onInit={instance => { flow.current = instance; }}
      fitView fitViewOptions={{ padding: 0.18, maxZoom: 1.15 }}
      minZoom={0.12} maxZoom={2} nodesConnectable={false} edgesReconnectable={false}
      deleteKeyCode={null} colorMode="dark"
      aria-label="MSFlix ontology relationships"
    >
      <Background variant={BackgroundVariant.Dots} color="#414247" gap={22} size={1} />
      <Controls showInteractive={false} />
      <MiniMap pannable zoomable nodeColor={node => node.data.kind === 'content' ? '#ed6757' : '#646168'}
        maskColor="#121315bb" bgColor="#1b1c1f" />
    </ReactFlow>
  </div>;
}

export function OntologyGraph({ active = true, refreshKey = 0, prefetch = false, renderCanvas = true }: {
  active?: boolean; refreshKey?: number; prefetch?: boolean; renderCanvas?: boolean;
}) {
  const [data, setData] = useState<Result>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [limit, setLimit] = useState(6);
  const [selectedId, setSelectedId] = useState<string>();
  const loaded = useRef(false);
  const refreshed = useRef(refreshKey);
  const inFlight = useRef(false);
  const load = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setLoading(true); setError('');
    try {
      const result = await getRayfinClient().functions.businessGraphSlice.invoke({ journeyLimit: limit });
      setData(result); loaded.current = true;
    } catch (err) { setError(safeError(err)); }
    finally { setLoading(false); inFlight.current = false; }
  }, [limit]);
  useEffect(() => {
    if ((!active && !prefetch) || loading) return;
    if (refreshed.current!==refreshKey || (!error && (!loaded.current || (data?.limit ?? 0) < limit))) {
      refreshed.current=refreshKey;
      void load();
    }
  }, [active, prefetch, load, data?.limit, limit, loading, error, refreshKey]);
  const scene = useMemo(() => {
    if (data?.state !== 'ready') return undefined;
    try { return { value: createGraphScene(data, search, limit) }; }
    catch (err) { return { error: safeError(err) }; }
  }, [data, search, limit]);
  const selected = data?.nodes.find(node => node.key === selectedId);
  const relationships = data?.edges.filter(edge => edge.from === selectedId || edge.to === selectedId) ?? [];
  return <section className="ontology-explorer" aria-label="Actual Ontology v2 graph" aria-busy={loading}>
    <div className="ontology-toolbar">
      <div><h2>Follow a customer journey</h2>
        <p>Customers, orders, offers and films, connected by the real business ontology.</p></div>
      <button disabled={loading} onClick={() => void load()}><ArrowsClockwise aria-hidden="true" />
        {loading ? 'Reading graph…' : 'Refresh graph'}</button>
    </div>
    {error && <div className="error-state" role="alert"><h3>Graph read unavailable</h3><p>{error}</p>
      {data && <p>The last successful graph remains visible.</p>}</div>}
    {loading && !data && <div className="ontology-loading" role="status">
      <span className="skeleton wide" /><p>Loading the actual ontology relationships…</p></div>}
    {data && data.state !== 'ready' && <div className="empty-state">
      <h3>{data.state === 'binding-mismatch' ? 'Gold ontology binding pending'
        : data.state === 'pending' ? 'Graph initial load pending' : 'No graph instances'}</h3><p>{data.message}</p></div>}
    {data?.state === 'ready' && <>
      <div className="ontology-filters">
        <label htmlFor="graph-search">Find a customer, film or identifier
          <input id="graph-search" type="search" value={search} onChange={event => {
            setSearch(event.target.value); setSelectedId(undefined);
          }} placeholder="Name, film, territory or order…" /></label>
        <label htmlFor="graph-limit">Journeys to load
          <select id="graph-limit" value={limit} onChange={event => {
            setLimit(Number(event.target.value)); setSelectedId(undefined);
          }}>{[6, 12, 24, 50].map(value => <option key={value} value={value}>{value} journeys</option>)}</select>
        </label>
      </div>
      {scene?.error && <p className="notice" role="alert">{scene.error}</p>}
      {scene?.value && <>
        <div className="ontology-legend" aria-label="Graph legend">
          {Object.entries(kindLabels).map(([kind, label]) => <span key={kind} className={`ontology-legend-${kind}`}>{label}</span>)}
          <span className="ontology-scope">{scene.value.nodes.length} nodes / {scene.value.edges.length} relationships</span>
        </div>
        {scene.value.nodes.length ? renderCanvas&&<GraphCanvas key={`${data.queried_at}:${search}:${limit}`}
          scene={scene.value} onSelect={setSelectedId} />
          : <div className="empty-state"><h3>No matching journeys</h3><p>Load more journeys or search another customer or film in this sample.</p></div>}
        <p className="ontology-hint">Drag the canvas to explore. Scroll to zoom. Select a node for its connections.
          <span>{scene.value.shownJourneys} of {scene.value.matchingJourneys} matching loaded journeys shown.</span></p>
      </>}
      {selected && <aside className="ontology-inspector" aria-label="Selected graph node">
        <div><small>{kindLabels[selected.type] ?? selected.type}</small><h3>{selected.label}</h3>
          <code>{selected.key}</code></div>
        <div><h3>Connected through the ontology</h3><ul>{relationships.map(edge => {
          const other = data.nodes.find(node => node.key === (edge.from === selectedId ? edge.to : edge.from));
          return <li key={`${edge.from}:${edge.type}:${edge.to}`}>
            <span>{relationshipLabels[edge.type] ?? edge.type}</span> {other?.label ?? other?.key}
          </li>;
        })}</ul></div>
      </aside>}
      <details className="ontology-provenance"><summary>Source and freshness</summary>
        <p>Read {dateLabel(data.queried_at)}. Up to {data.limit} source paths per query.
          Returning to this tab keeps the last successful result until you refresh.</p>
        <small>Ontology {data.source.ontology_id}<br />GraphModel {data.source.graph_model_id}</small>
      </details>
    </>}
  </section>;
}
