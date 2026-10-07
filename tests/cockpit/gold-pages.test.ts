import{describe,expect,it,vi}from'vitest';
vi.mock('../../apps/cockpit/src/services/rayfinClient',()=>({getRayfinClient:vi.fn()}));
import{goldSnapshot}from'../../apps/cockpit/src/services/goldViews';
import type{GoldPages}from'../../apps/cockpit/rayfin/functions/src/gold-pages';
describe('Gold business-page adapter',()=>{
  it('retains an empty Gold collection instead of substituting operational catalog or customers',()=>{
    const result=goldSnapshot({catalog:[],customers:[],offers:[],orders:[],sessions:[],campaigns:[]}as unknown as GoldPages);
    expect(result.content).toEqual([]);expect(result.customers).toEqual([]);expect(result.rentals).toEqual([]);
  });
  it('accepts the actual nullable purchase policy without losing the entire Gold catalog',()=>{
    const pages={catalog:[],customers:[],orders:[],sessions:[],campaigns:[],offers:[{
      offer_key:'film:FR:PURCHASE',content_key:'film',territory:'FR',currency:'EUR',
      transaction_type:'EST',price_minor:'1299',start_window_hours:null,play_window_hours:null,
    }]}as unknown as GoldPages;
    expect(goldSnapshot(pages).offers[0]).toMatchObject({transaction_type:'EST',price_minor:1299,start_window_hours:0,play_window_hours:0});
    pages.offers[0].transaction_type='TVOD';
    expect(()=>goldSnapshot(pages)).toThrow('exact safe integer');
  });
});
