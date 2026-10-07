import{describe,expect,it,vi}from'vitest';
vi.mock('../../apps/cockpit/src/services/rayfinClient',()=>({getRayfinClient:vi.fn()}));
import{goldSnapshot}from'../../apps/cockpit/src/services/goldViews';
import type{GoldPages}from'../../apps/cockpit/rayfin/functions/src/gold-pages';
describe('Gold business-page adapter',()=>{
  it('retains an empty Gold collection instead of substituting operational catalog or customers',()=>{
    const result=goldSnapshot({catalog:[],customers:[],offers:[],orders:[],sessions:[],campaigns:[]}as unknown as GoldPages);
    expect(result.content).toEqual([]);expect(result.customers).toEqual([]);expect(result.rentals).toEqual([]);
  });
});
