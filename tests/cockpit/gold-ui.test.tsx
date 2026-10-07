import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import{cleanup,render,screen}from'@testing-library/react';
const mode=vi.hoisted(()=>({fail:true}));
vi.mock('../../apps/cockpit/src/services/rayfinClient',()=>({
  getRayfinClient:()=>({functions:{businessDashboard:{invoke:async()=>{
    if(mode.fail)throw new Error('Gold load unavailable');
    return {source:{name:'MSFlixGold',item_id:'actual-gold',views:['gold.commercial_activity']},
      state:'empty',freshness:{queried_at:'2026-10-07T13:57:50Z',published_at:'2026-10-07T13:57:06Z',
        publication_run_id:'actual-empty-publication',order_lines:'0'},commercial:[],playback:[],campaigns:[],
      dimensions:{customers:'120',content:'5'}};
  }}}}),
}));
import{GoldBusinessDashboard}from'../../apps/cockpit/src/components/GoldBusinessDashboard';
afterEach(cleanup);
beforeEach(()=>{mode.fail=true;});
describe('Gold business dashboard error boundary',()=>{
  it('shows Gold connection failure without substituting real operational KPIs',async()=>{
    render(<GoldBusinessDashboard/>);
    expect(await screen.findByRole('alert')).toHaveTextContent('Gold load unavailable');
    expect(screen.getByText(/Operational SQL is not used as a fallback/)).toBeInTheDocument();
    expect(screen.queryByText('Recorded sales')).not.toBeInTheDocument();
  });
  it('shows the actual published zero-order state without operational sales figures',async()=>{
    mode.fail=false;
    render(<GoldBusinessDashboard/>);
    expect(await screen.findByText('No curated business activity')).toBeInTheDocument();
    expect(screen.getByText('Publication run: actual-empty-publication')).toBeInTheDocument();
    expect(screen.queryByText('Recorded sales')).not.toBeInTheDocument();
  });
});
