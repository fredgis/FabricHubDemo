import { cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

const invoke=vi.hoisted(()=>vi.fn());
vi.mock('../../apps/cockpit/src/services/rayfinClient',()=>({
  getRayfinClient:()=>({functions:{businessGraphSlice:{invoke}}}),
}));
import { OntologyGraph } from '../../apps/cockpit/src/components/OntologyGraph';
afterEach(cleanup);

it('prefetches six genuine source paths once and reuses the result when the tab opens',async()=>{
  invoke.mockResolvedValue({
    state:'ready',limit:6,queried_at:'2026-10-08T20:00:00Z',generation:2,
    source:{ontology_id:'fixture',graph_model_id:'fixture'},message:'Fixture',
    nodes:[
      {key:'customer:c1',type:'customer',label:'Customer'},
      {key:'rental:r1',type:'rental',label:'Order'},
      {key:'offer:o1',type:'offer',label:'Offer'},
      {key:'content:f1',type:'content',label:'Film'},
    ],
    edges:[
      {from:'customer:c1',to:'rental:r1',type:'customer_order'},
      {from:'rental:r1',to:'offer:o1',type:'order_offer'},
      {from:'offer:o1',to:'content:f1',type:'offer_content'},
    ],
  });
  const view=render(<OntologyGraph active={false} prefetch renderCanvas={false}/>);
  await waitFor(()=>expect(view.getByText(/Read .*UTC/)).toBeInTheDocument());
  expect(invoke).toHaveBeenCalledExactlyOnceWith({journeyLimit:6});
  expect(view.container.querySelector('.ontology-canvas')).toBeNull();
  view.rerender(<OntologyGraph active prefetch renderCanvas={false}/>);
  expect(invoke).toHaveBeenCalledOnce();
});
