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
});
