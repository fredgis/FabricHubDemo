import { graphlib, layout } from '@dagrejs/dagre';
import { MarkerType, Position, type Edge, type Node } from '@xyflow/react';
import type { OntologyGraph } from '../../rayfin/functions/src/ontology-graph';

export type BusinessNodeData = {
  title: string;
  kind: string;
  key: string;
  caption: string;
};
export type BusinessNode = Node<BusinessNodeData, 'business'>;
export type GraphScene = {
  nodes: BusinessNode[];
  edges: Edge[];
  shownJourneys: number;
  matchingJourneys: number;
};

export const kindLabels: Record<string, string> = {
  customer: 'Customer', rental: 'Order', offer: 'Offer', content: 'Film',
};
export const relationshipLabels: Record<string, string> = {
  customer_order: 'placed', order_offer: 'uses offer', offer_content: 'for film',
};

export function graphNodeTitle(node: OntologyGraph['nodes'][number]): string {
  if (node.type === 'rental') return `Order ${node.label.slice(0, 8)}`;
  if (node.type === 'offer') {
    const match = node.label.match(/:([A-Z]{2}):(RENTAL|PURCHASE)$/);
    if (match) return `${match[2] === 'RENTAL' ? 'Rental' : 'Purchase'} / ${match[1]}`;
  }
  return node.label;
}

export function createGraphScene(result: OntologyGraph, search = '', limit = 6): GraphScene {
  if (!Number.isInteger(limit) || limit < 1 || limit > 50) throw new Error('Graph journey limit must be 1-50.');
  const byId = new Map(result.nodes.map(node => [node.key, node]));
  if (result.edges.some(edge => !byId.has(edge.from) || !byId.has(edge.to))) {
    throw new Error('The ontology returned a relationship with a missing endpoint.');
  }
  const filter = search.trim().toLocaleLowerCase();
  const journeys: { ids: Set<string>; edges: OntologyGraph['edges'] }[] = [];
  for (const order of result.nodes.filter(node => node.type === 'rental')) {
    const customers = result.edges.filter(edge => edge.type === 'customer_order' && edge.to === order.key);
    const offers = result.edges.filter(edge => edge.type === 'order_offer' && edge.from === order.key);
    const offerIds = new Set(offers.map(edge => edge.to));
    const films = result.edges.filter(edge => edge.type === 'offer_content' && offerIds.has(edge.from));
    if (!customers.length || !offers.length || !films.length) continue;
    const edges = [...customers, ...offers, ...films];
    const ids = new Set(edges.flatMap(edge => [edge.from, edge.to]));
    if (filter && ![...ids].some(id => {
      const node = byId.get(id)!;
      return `${node.label} ${node.key} ${graphNodeTitle(node)}`.toLocaleLowerCase().includes(filter);
    })) continue;
    journeys.push({ ids, edges });
  }
  const chosen = journeys.slice(0, limit);
  const visible = new Set(chosen.flatMap(journey => [...journey.ids]));
  const links = new Map(chosen.flatMap(journey => journey.edges).map(edge =>
    [`${edge.from}|${edge.type}|${edge.to}`, edge]));
  const graph = new graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  graph.setGraph({ rankdir: 'LR', ranksep: 105, nodesep: 24, marginx: 30, marginy: 30 });
  for (const id of visible) graph.setNode(id, { width: 212, height: 88 });
  for (const edge of links.values()) graph.setEdge(edge.from, edge.to);
  layout(graph);
  const nodes: BusinessNode[] = [...visible].map(id => {
    const node = byId.get(id)!;
    const point = graph.node(id);
    const title = graphNodeTitle(node);
    return {
      id, type: 'business', width: 212, height: 88,
      position: { x: point.x - 106, y: point.y - 44 },
      sourcePosition: Position.Right, targetPosition: Position.Left,
      data: { title, kind: node.type, key: node.key, caption: kindLabels[node.type] ?? node.type },
      ariaLabel: `${kindLabels[node.type] ?? node.type}: ${title}`,
    };
  });
  const edges: Edge[] = [...links].map(([id, edge]) => ({
    id, source: edge.from, target: edge.to, type: 'smoothstep',
    label: relationshipLabels[edge.type] ?? edge.type,
    markerEnd: { type: MarkerType.ArrowClosed, color: '#b78379', width: 18, height: 18 },
    style: { stroke: '#b78379', strokeWidth: 1.8 },
    labelStyle: { fill: '#e0d5d1', fontSize: 11 },
    labelBgStyle: { fill: '#17181b', fillOpacity: 0.96 },
    labelBgPadding: [7, 4], labelBgBorderRadius: 4,
    ariaLabel: `${byId.get(edge.from)!.label} ${relationshipLabels[edge.type] ?? edge.type} ${byId.get(edge.to)!.label}`,
  }));
  return { nodes, edges, shownJourneys: chosen.length, matchingJourneys: journeys.length };
}
