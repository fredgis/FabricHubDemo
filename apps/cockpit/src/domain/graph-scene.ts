import { graphlib, layout } from '@dagrejs/dagre';
import { MarkerType, Position, type Edge, type Node } from '@xyflow/react';
import type { OntologyGraph, OntologyGraphNode } from '../../rayfin/functions/src/ontology-graph';

export type BusinessNodeData = {
  title: string;
  kind: string;
  key: string;
  caption: string;
  createdAt?: string;
  status?: string;
};
export type BusinessNode = Node<BusinessNodeData, 'business'>;
export type GraphScene = {
  nodes: BusinessNode[];
  edges: Edge[];
  orders: { node: OntologyGraphNode; customer: string; films: string[] }[];
  shownJourneys: number;
  matchingJourneys: number;
};

export const kindLabels: Record<string, string> = {
  customer: 'Customer', rental: 'Order', offer: 'Offer', content: 'Film',
  distributor: 'Distributor', playback: 'Viewing session',
};
export const relationshipLabels: Record<string, string> = {
  customer_order: 'placed', order_offer: 'uses offer', offer_content: 'for film',
  content_distributor: 'distributed by', playback_order: 'belongs to order', playback_content: 'plays film',
};

export function graphNodeTitle(node: OntologyGraphNode): string {
  if (node.type === 'rental') return `Order ${node.label.slice(0, 8)}`;
  if (node.type === 'playback') return `Session ${node.label.slice(0, 8)}`;
  if (node.type === 'offer') {
    const match = node.label.match(/:([A-Z]{2}):(RENTAL|PURCHASE)$/);
    if (match) return `${match[2] === 'RENTAL' ? 'Rental' : 'Purchase'} / ${match[1]}`;
  }
  return node.label;
}

export function createGraphScene(result: OntologyGraph, search = '', limit = 12, focusedOrder?: string): GraphScene {
  if (!Number.isInteger(limit) || limit < 1 || limit > 50) throw new Error('Graph journey limit must be 1-50.');
  const byId = new Map(result.nodes.map(node => [node.key, node]));
  if (result.edges.some(edge => !byId.has(edge.from) || !byId.has(edge.to))) {
    throw new Error('The ontology returned a relationship with a missing endpoint.');
  }
  const filter = search.trim().toLocaleLowerCase();
  const orders = [...byId.values()].filter(node => node.type === 'rental').sort((a, b) =>
    (Date.parse(b.created_at ?? '') || 0) - (Date.parse(a.created_at ?? '') || 0)
    || b.key.localeCompare(a.key)).slice(0, limit);
  const journeys: { ids: Set<string>; edges: OntologyGraph['edges']; order: GraphScene['orders'][number] }[] = [];
  for (const order of orders) {
    const customers = result.edges.filter(edge => edge.type === 'customer_order' && edge.to === order.key);
    const offers = result.edges.filter(edge => edge.type === 'order_offer' && edge.from === order.key);
    const offerIds = new Set(offers.map(edge => edge.to));
    const films = result.edges.filter(edge => edge.type === 'offer_content' && offerIds.has(edge.from));
    if (!customers.length || !offers.length || !films.length) continue;
    const filmIds = new Set(films.map(edge => edge.to));
    const distributors = result.edges.filter(edge => edge.type === 'content_distributor' && filmIds.has(edge.from));
    const sessions = result.edges.filter(edge => edge.type === 'playback_order' && edge.to === order.key);
    const sessionIds = new Set(sessions.map(edge => edge.from));
    const sessionFilms = result.edges.filter(edge => edge.type === 'playback_content'
      && sessionIds.has(edge.from) && filmIds.has(edge.to));
    const edges = [...customers, ...offers, ...films, ...distributors, ...sessions, ...sessionFilms];
    const ids = new Set(edges.flatMap(edge => [edge.from, edge.to]));
    if (filter && ![...ids].some(id => {
      const node = byId.get(id)!;
      return `${node.label} ${node.key} ${graphNodeTitle(node)} ${node.status ?? ''} ${node.created_at ?? ''}`
        .toLocaleLowerCase().includes(filter);
    })) continue;
    journeys.push({ ids, edges, order: {
      node: order, customer: customers.map(edge => byId.get(edge.from)!.label).join(', '),
      films: [...filmIds].map(id => byId.get(id)!.label),
    } });
  }
  const chosen = focusedOrder ? journeys.filter(journey => journey.order.node.key === focusedOrder) : journeys;
  const visible = new Set(chosen.flatMap(journey => [...journey.ids]));
  const links = new Map(chosen.flatMap(journey => journey.edges).map(edge =>
    [`${edge.from}|${edge.type}|${edge.to}`, edge]));
  const graph = new graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  graph.setGraph({ rankdir: 'LR', ranksep: 105, nodesep: 30, marginx: 30, marginy: 30 });
  for (const id of visible) graph.setNode(id, { width: 232, height: 104 });
  for (const edge of links.values()) {
    // Sessions sit beyond the film; rendered arrows still follow the real session-to-film/order links.
    if (edge.type.startsWith('playback_')) graph.setEdge(edge.to, edge.from);
    else graph.setEdge(edge.from, edge.to);
  }
  layout(graph);
  const nodes: BusinessNode[] = [...visible].map(id => {
    const node = byId.get(id)!;
    const point = graph.node(id);
    const title = graphNodeTitle(node);
    return {
      id, type: 'business', width: 232, height: 104, selected: id === focusedOrder,
      position: { x: point.x - 116, y: point.y - 52 },
      sourcePosition: Position.Right, targetPosition: Position.Left,
      data: { title, kind: node.type, key: node.key, caption: kindLabels[node.type] ?? node.type,
        createdAt: node.created_at, status: node.status },
      ariaLabel: `${kindLabels[node.type] ?? node.type}: ${title}${node.created_at ? `, created ${node.created_at}` : ''}${node.status ? `, ${node.status}` : ''}`,
    };
  });
  const edges: Edge[] = [...links].map(([id, edge]) => ({
    id, source: edge.from, target: edge.to, type: 'smoothstep',
    sourceHandle: edge.type.startsWith('playback_') ? 'source-left' : 'source-right',
    targetHandle: edge.type.startsWith('playback_') ? 'target-right' : 'target-left',
    label: relationshipLabels[edge.type] ?? edge.type,
    markerEnd: { type: MarkerType.ArrowClosed, color: '#b78379', width: 18, height: 18 },
    style: { stroke: '#b78379', strokeWidth: 1.8 },
    labelStyle: { fill: '#e0d5d1', fontSize: 11 },
    labelBgStyle: { fill: '#17181b', fillOpacity: 0.96 },
    labelBgPadding: [7, 4], labelBgBorderRadius: 4,
    ariaLabel: `${byId.get(edge.from)!.label} ${relationshipLabels[edge.type] ?? edge.type} ${byId.get(edge.to)!.label}`,
  }));
  return { nodes, edges, orders: journeys.map(journey => journey.order),
    shownJourneys: chosen.length, matchingJourneys: journeys.length };
}
