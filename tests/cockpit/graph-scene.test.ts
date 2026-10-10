import { describe, expect, it } from 'vitest';
import { createGraphScene, graphNodeTitle } from '../../apps/cockpit/src/domain/graph-scene';
import type { OntologyGraph } from '../../apps/cockpit/rayfin/functions/src/ontology-graph';

const result: OntologyGraph = {
  source:{workspace_id:'fixture',ontology_id:'fixture',graph_model_id:'fixture',gold_item_id:'fixture'},
  state:'ready',queried_at:'2026-10-07T21:00:00Z',generation:2,message:'Actual fixture',limit:50,
  nodes:[
    {key:'customer:C1',type:'customer',label:'Camille Laurent'},
    {key:'rental:R1',type:'rental',label:'R1'},
    {key:'offer:F1:FR:RENTAL',type:'offer',label:'F1:FR:RENTAL'},
    {key:'content:F1',type:'content',label:'Sintel'},
  ],
  edges:[
    {from:'customer:C1',to:'rental:R1',type:'customer_order'},
    {from:'rental:R1',to:'offer:F1:FR:RENTAL',type:'order_offer'},
    {from:'offer:F1:FR:RENTAL',to:'content:F1',type:'offer_content'},
  ],
};
describe('real ontology graph scene',()=>{
  it('renders every actual relation with a direction and only its actual endpoints',()=>{
    const scene=createGraphScene(result);
    expect(scene.nodes).toHaveLength(4);expect(scene.edges).toHaveLength(3);
    expect(scene.edges.map(edge=>[edge.source,edge.target])).toEqual(result.edges.map(edge=>[edge.from,edge.to]));
    expect(scene.edges.every(edge=>edge.markerEnd)).toBe(true);
    expect(scene.nodes.every(node=>Number.isFinite(node.position.x)&&Number.isFinite(node.position.y))).toBe(true);
    expect(scene.nodes[0].position.x).toBeLessThan(scene.nodes[3].position.x);
  });
  it('filters whole journeys instead of leaving orphan nodes',()=>{
    expect(createGraphScene(result,'sintel').nodes).toHaveLength(4);
    expect(createGraphScene(result,'Camille').edges).toHaveLength(3);
    expect(createGraphScene(result,'not-in-source').nodes).toHaveLength(0);
  });
  it('does not manufacture edges to fix a malformed source result',()=>{
    expect(()=>createGraphScene({...result,nodes:result.nodes.slice(1)})).toThrow('missing endpoint');
    expect(()=>createGraphScene(result,'',0)).toThrow('1-50');
  });
  it('uses human-readable business labels while preserving identifiers',()=>{
    expect(graphNodeTitle(result.nodes[2])).toBe('Rental / FR');
    expect(createGraphScene(result).nodes[2].data.key).toBe('offer:F1:FR:RENTAL');
  });
  const extended = (): OntologyGraph => ({
    ...result,
    nodes: [
      ...result.nodes.map(node => node.type === 'rental' ? { ...node, created_at: '2026-10-09T12:00:00Z', status: 'active' } : node),
      { key: 'rental:R2', type: 'rental', label: 'R2', created_at: '2026-10-10T12:00:00.001Z', status: 'purchased' },
      { key: 'distributor:D1', type: 'distributor', label: 'Fixture distributor' },
      { key: 'playback:P1', type: 'playback', label: 'P1', status: 'playing' },
      { key: 'playback:P2', type: 'playback', label: 'P2', status: 'completed' },
    ],
    edges: [
      ...result.edges,
      { from: 'customer:C1', to: 'rental:R2', type: 'customer_order' },
      { from: 'rental:R2', to: 'offer:F1:FR:RENTAL', type: 'order_offer' },
      { from: 'content:F1', to: 'distributor:D1', type: 'content_distributor' },
      { from: 'playback:P1', to: 'rental:R1', type: 'playback_order' },
      { from: 'playback:P1', to: 'content:F1', type: 'playback_content' },
      { from: 'playback:P2', to: 'rental:R2', type: 'playback_order' },
      { from: 'playback:P2', to: 'content:F1', type: 'playback_content' },
    ],
  });
  it('orders by creation time and then identifier before applying the local search', () => {
    const data = extended();
    data.nodes.push({ key: 'rental:R3', type: 'rental', label: 'R3', created_at: '2026-10-10T12:00:00.001Z' });
    data.edges.push({ from: 'customer:C1', to: 'rental:R3', type: 'customer_order' },
      { from: 'rental:R3', to: 'offer:F1:FR:RENTAL', type: 'order_offer' });
    expect(createGraphScene(data).orders.map(order => order.node.label)).toEqual(['R3', 'R2', 'R1']);
    expect(createGraphScene(data, 'R1', 2).shownJourneys).toBe(0);
    expect(createGraphScene(data, 'R1', 3).shownJourneys).toBe(1);
    data.nodes.find(node => node.key === 'rental:R3')!.created_at = '2026-10-10T12:00:00Z';
    expect(createGraphScene(data).orders[0].node.key).toBe('rental:R2');
  });
  it('focuses one order while retaining the chronological list and only that order’s sessions', () => {
    const scene = createGraphScene(extended(), '', 12, 'rental:R2');
    expect(scene.orders.map(order => order.node.key)).toEqual(['rental:R2', 'rental:R1']);
    expect(scene.shownJourneys).toBe(1); expect(scene.matchingJourneys).toBe(2);
    expect(scene.nodes.map(node => node.id)).toEqual(expect.arrayContaining(['rental:R2', 'playback:P2', 'distributor:D1']));
    expect(scene.nodes.map(node => node.id)).not.toContain('playback:P1');
    expect(scene.nodes.map(node => node.id)).not.toContain('rental:R1');
    expect(scene.nodes.find(node => node.id === 'rental:R2')?.selected).toBe(true);
  });
  it('puts playback on the far side of films without reversing its actual arrows', () => {
    const scene = createGraphScene(extended(), '', 12, 'rental:R2');
    const film = scene.nodes.find(node => node.id === 'content:F1')!;
    const playback = scene.nodes.find(node => node.id === 'playback:P2')!;
    expect(playback.position.x).toBeGreaterThan(film.position.x);
    expect(scene.nodes.find(node => node.id === 'distributor:D1')!.position.x).toBeGreaterThan(film.position.x);
    expect(scene.edges.find(edge => edge.source === playback.id && edge.target === film.id)).toMatchObject({
      sourceHandle: 'source-left', targetHandle: 'target-right', label: 'plays film',
    });
    expect(scene.nodes.every(node => Number.isFinite(node.position.x) && Number.isFinite(node.position.y))).toBe(true);
  });
  it('searches distributors and session states through their own complete order paths', () => {
    expect(createGraphScene(extended(), 'Fixture distributor').shownJourneys).toBe(2);
    const scene = createGraphScene(extended(), 'completed');
    expect(scene.orders.map(order => order.node.key)).toEqual(['rental:R2']);
    expect(scene.nodes).toHaveLength(6);
  });
  it('deduplicates source nodes and edges without adding a playback-to-customer link', () => {
    const data = extended(); data.nodes.push(data.nodes[1]); data.edges.push(data.edges[0]);
    const scene = createGraphScene(data);
    expect(scene.orders).toHaveLength(2);
    expect(new Set(scene.nodes.map(node => node.id)).size).toBe(scene.nodes.length);
    expect(new Set(scene.edges.map(edge => edge.id)).size).toBe(scene.edges.length);
    expect(scene.edges.some(edge => edge.source.startsWith('playback:') && edge.target.startsWith('customer:'))).toBe(false);
  });
});
