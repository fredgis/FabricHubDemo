import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowsClockwise, Buildings, FilmSlate, PlayCircle, ShoppingBag, Ticket, UserCircle } from '@phosphor-icons/react';
import {
  Background, BackgroundVariant, Controls, Handle, MiniMap, Position, ReactFlow,
  useNodesState, type NodeProps, type Edge,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './OntologyGraph.css';
import { getRayfinClient } from '@/services/rayfinClient';
import { dateLabel, money, safeError } from '@/services/business';
import { createGraphScene, graphNodeTitle, kindLabels, relationshipLabels, type BusinessNode, type GraphScene } from '@/domain/graph-scene';
import type { OntologyGraph as Result } from '../../rayfin/functions/src/ontology-graph';

const icons = { customer: UserCircle, rental: ShoppingBag, offer: Ticket, content: FilmSlate,
  distributor: Buildings, playback: PlayCircle };
const shortDate = (value: string) => new Intl.DateTimeFormat('en', {
  month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23', timeZone: 'UTC',
}).format(new Date(value)) + ' UTC';
const BusinessNodeCard = memo(function BusinessNodeCard({ data, selected }: NodeProps<BusinessNode>) {
  const Icon = icons[data.kind as keyof typeof icons] ?? FilmSlate;
  return <div className={`ontology-node ontology-node-${data.kind}${selected ? ' is-selected' : ''}`}>
    <Handle id="target-left" type="target" position={Position.Left} isConnectable={false} />
    {data.kind === 'playback' && <Handle id="source-left" type="source" position={Position.Left} isConnectable={false} />}
    <span className="ontology-node-icon"><Icon size={24} aria-hidden="true" /></span>
    <div><span className="ontology-node-kind">{data.caption}{data.status && ` / ${data.status.replaceAll('_', ' ')}`}</span>
      <strong title={data.title}>{data.title}</strong>
      {data.createdAt && <time dateTime={data.createdAt} title={dateLabel(data.createdAt)}>{shortDate(data.createdAt)}</time>}</div>
    <Handle id="source-right" type="source" position={Position.Right} isConnectable={false} />
    {['content', 'rental'].includes(data.kind) && <Handle id="target-right" type="target" position={Position.Right} isConnectable={false} />}
  </div>;
});
const nodeTypes = { business: BusinessNodeCard };
export type GraphReadState = { loading: boolean; queriedAt: string | null };

export function GraphCanvas({ scene, onSelect }: { scene: GraphScene; onSelect: (id: string | undefined) => void }) {
  const [nodes, setNodes, onNodesChange] = useNodesState<BusinessNode>(scene.nodes);
  useEffect(() => { setNodes(scene.nodes); }, [scene.nodes, setNodes]);
  const selectionChanged = useCallback(({ nodes: selected }: { nodes: BusinessNode[] }) => {
    onSelect(selected[0]?.id);
  }, [onSelect]);
  return <div className="ontology-canvas" aria-label="Interactive orders, films, distributors and viewing sessions">
    <ReactFlow<BusinessNode, Edge>
      nodes={nodes} edges={scene.edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange}
      onSelectionChange={selectionChanged} onPaneClick={() => onSelect(undefined)}
      fitView fitViewOptions={{ padding: 0.18, maxZoom: 1.15 }}
      minZoom={0.08} maxZoom={2} nodesConnectable={false} edgesReconnectable={false}
      deleteKeyCode={null} colorMode="dark"
      aria-label="MSFlix ontology relationships"
    >
      <Background variant={BackgroundVariant.Dots} color="#414247" gap={22} size={1} />
      <Controls showInteractive={false} />
      <MiniMap pannable zoomable nodeColor={node => node.data.kind === 'content' ? '#ed6757' : '#817c86'}
        maskColor="#121315bb" bgColor="#1b1c1f" />
    </ReactFlow>
  </div>;
}

export function OntologyGraph({ active = true, refreshKey = 0, prefetch = false, renderCanvas = true, onRead }: {
  active?: boolean; refreshKey?: number; prefetch?: boolean; renderCanvas?: boolean;
  onRead?: (state: GraphReadState) => void;
}) {
  const [data, setData] = useState<Result>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [limit, setLimit] = useState(12);
  const [focusedOrder, setFocusedOrder] = useState<string>();
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
      const newest = result.nodes.find(node => node.type === 'rental')?.key;
      setFocusedOrder(newest); setSelectedId(newest);
    } catch (err) { setError(safeError(err)); }
    finally { setLoading(false); inFlight.current = false; }
  }, [limit]);
  useEffect(() => {
    if ((!active && !prefetch) || loading) return;
    if (refreshed.current !== refreshKey || (!error && (!loaded.current || (data?.limit ?? 0) < limit))) {
      refreshed.current = refreshKey;
      void load();
    }
  }, [active, prefetch, load, data?.limit, limit, loading, error, refreshKey]);
  useEffect(() => { onRead?.({ loading, queriedAt: data?.queried_at ?? null }); }, [loading, data?.queried_at, onRead]);
  const scene = useMemo(() => {
    if (data?.state !== 'ready') return undefined;
    try { return { value: createGraphScene(data, search, limit, focusedOrder) }; }
    catch (err) { return { error: safeError(err) }; }
  }, [data, search, limit, focusedOrder]);
  const visible = new Set(scene?.value?.nodes.map(node => node.id));
  const selected = visible.has(selectedId ?? '') ? data?.nodes.find(node => node.key === selectedId) : undefined;
  const relationships = data?.edges.filter(edge => visible.has(edge.from) && visible.has(edge.to)
    && (edge.from === selectedId || edge.to === selectedId)) ?? [];
  return <section className="ontology-explorer" aria-label="Actual Ontology v2 graph" aria-busy={loading}>
    <div className="ontology-toolbar">
      <div><h2>Latest transactions, connected</h2>
        <p>Newest published orders first, with their customers, films, distributors and viewing sessions.</p></div>
      <button disabled={loading} onClick={() => void load()}><ArrowsClockwise aria-hidden="true" />
        {loading ? 'Reading graph…' : 'Refresh graph'}</button>
    </div>
    {error && <div className="error-state" role="alert"><h3>Graph read unavailable</h3><p>{error}</p>
      <p>{data ? 'The last successful graph remains visible. ' : ''}Use Refresh graph to retry.</p></div>}
    {loading && !data && <div className="ontology-loading" role="status">
      <span className="skeleton wide" /><p>Reading the newest orders and their ontology relationships…</p></div>}
    {loading && data && <p role="status" className="permission-note">Reading the latest graph. The previous read remains visible.</p>}
    {data && data.state !== 'ready' && <div className="empty-state" role="status">
      <h3>{data.state === 'binding-mismatch' ? 'Gold ontology binding pending'
        : data.state === 'pending' ? 'Graph read pending' : 'No published order paths'}</h3><p>{data.message}</p></div>}
    {data?.state === 'ready' && <>
      <div className="ontology-filters">
        <label htmlFor="graph-search">Search the loaded orders and connections
          <input id="graph-search" type="search" value={search} aria-describedby="graph-search-scope" onChange={event => {
            setSearch(event.target.value); setFocusedOrder(undefined); setSelectedId(undefined);
          }} placeholder="Customer, film, distributor or identifier" /></label>
        <label htmlFor="graph-limit">Recent orders to load
          <select id="graph-limit" value={limit} disabled={loading} onChange={event => {
            setLimit(Number(event.target.value)); setFocusedOrder(undefined); setSelectedId(undefined);
          }}>{[6, 12, 24, 50].map(value => <option key={value} value={value}>{value} latest orders</option>)}</select>
        </label>
      </div>
      <p id="graph-search-scope" className="ontology-search-scope">Search stays within the latest {Math.min(limit, data.limit)} loaded orders, not the full history.</p>
      {data.context?.playback_truncated && <p className="notice" role="status">Viewing sessions are capped at {data.context.playback_limit} for these orders.
        This is not a complete session history; orders still follow creation time.</p>}
      {data.context?.distributors_truncated && <p className="notice" role="status">Distributor relationships are capped at {data.context.distributor_limit} for these films.</p>}
      {data.context && !data.nodes.some(node => node.type === 'distributor') && <p className="ontology-context-note">
        No distributor relationship is published for the loaded films.</p>}
      {scene?.error && <p className="notice" role="alert">{scene.error}</p>}
      {scene?.value && <>
        <div className="ontology-legend" aria-label="Graph legend">
          {Object.entries(kindLabels).map(([kind, label]) => <span key={kind} className={`ontology-legend-${kind}`}>{label}</span>)}
          <span className="ontology-scope">{scene.value.nodes.length} nodes / {scene.value.edges.length} relationships</span>
        </div>
        {scene.value.orders.length ? <div className="ontology-workbench">
          <aside className="ontology-latest" aria-labelledby="graph-order-list-title">
            <h3 id="graph-order-list-title">Newest first</h3>
            <p>Select an order to isolate its connections.</p>
            <button className="ontology-show-all" aria-pressed={!focusedOrder} onClick={() => {
              setFocusedOrder(undefined); setSelectedId(undefined);
            }}>Show all {scene.value.orders.length} orders</button>
            <ol aria-label="Orders, newest first">{scene.value.orders.map(({ node, customer, films }, index) => <li key={node.key}>
              <button aria-pressed={focusedOrder === node.key} onClick={() => { setFocusedOrder(node.key); setSelectedId(node.key); }}>
                <span className="ontology-order-heading"><span aria-hidden="true">{index + 1}.</span><strong>{graphNodeTitle(node)}</strong></span>
                {node.created_at && <time dateTime={node.created_at}>{dateLabel(node.created_at)}</time>}
                <span>{customer}</span><span className="ontology-order-film">{films.join(', ')}</span>
              </button>
            </li>)}</ol>
          </aside>
          {renderCanvas && <GraphCanvas key={`${data.queried_at}:${search}:${limit}:${focusedOrder ?? 'all'}`}
            scene={scene.value} onSelect={setSelectedId} />}
        </div> : <div className="empty-state"><h3>No matching orders</h3>
          <p>Clear the search or load more recent orders. Search does not query the full ontology.</p></div>}
        <p className="ontology-hint">Pan or zoom the graph. Select a node for its details and directed connections.
          <span>{scene.value.shownJourneys} of {scene.value.matchingJourneys} matching orders shown.</span></p>
        <p className="ontology-context-note">Sessions belong only to these orders, not to every viewer of the same film.
          Orders without sessions or a known distributor remain visible.</p>
      </>}
      {selected && <aside className="ontology-inspector" aria-label="Selected graph node">
        <div><small>{kindLabels[selected.type] ?? selected.type}</small><h3>{selected.label}</h3>
          <code>{selected.key}</code>
          <dl>
            {selected.created_at && <><dt>Order created</dt><dd><time dateTime={selected.created_at}>{dateLabel(selected.created_at)}</time></dd></>}
            {selected.status && <><dt>Recorded status</dt><dd>{selected.status.replaceAll('_', ' ')}</dd></>}
            {selected.amount_minor !== undefined && selected.currency && <><dt>Recorded amount</dt><dd>{money(selected.amount_minor, selected.currency)}</dd></>}
            {selected.position_seconds !== undefined && <><dt>Playback position</dt><dd>{selected.position_seconds} seconds</dd></>}
          </dl>
        </div>
        <div><h3>Directed connections in this view</h3><ul>{relationships.map(edge => {
          const from = data.nodes.find(node => node.key === edge.from)!;
          const to = data.nodes.find(node => node.key === edge.to)!;
          return <li key={`${edge.from}:${edge.type}:${edge.to}`}>
            {graphNodeTitle(from)} <span>{relationshipLabels[edge.type] ?? edge.type}</span> {graphNodeTitle(to)}
          </li>;
        })}</ul></div>
      </aside>}
      <details className="ontology-provenance"><summary>Source and freshness</summary>
        <p>Read {dateLabel(data.queried_at)}. Orders are sorted by creation time, newest first, then by order ID.
          Dates on orders are transaction timestamps, not publication times.</p>
        <p>New transactions appear after Gold publication and the Ontology GraphModel refresh.
          Refresh graph reads that GraphModel; it does not start publication or refresh the model.
          Returning to this tab keeps the last successful read until you refresh.</p>
        <p>Distributors and sessions are read through existing ontology relationships.
          Sessions have no timestamp in this ontology and are ordered by identifier, not by recency.</p>
        <small>Ontology {data.source.ontology_id}<br />GraphModel {data.source.graph_model_id}</small>
      </details>
    </>}
  </section>;
}
