import { describe,expect,it } from 'vitest';
import { dashboardFromRows } from '../../apps/cockpit/rayfin/functions/src/gold-dashboard';
describe('Gold-only curated dashboard contract',()=>{
  it('does not present operational ledger counts as Gold while publication is missing',()=>{
    const result=dashboardFromRows({workspace_id:'workspace',item_id:'gold',name:'MSFlixGold'},
      {commercial:[],playback:[],campaigns:[],counts:[{customers:'0',content:'0'}],publication:[]},new Date('2026-10-07T13:00:00Z'));
    expect(result.state).toBe('unpublished');
    expect(result.source.name).toBe('MSFlixGold');
    expect(result.commercial).toEqual([]);
    expect(result.freshness.published_at).toBeNull();
  });
  it('retains exact Gold minor units and actual publication freshness',()=>{
    const result=dashboardFromRows({workspace_id:'workspace',item_id:'gold',name:'MSFlixGold'},
      {commercial:[{currency:'EUR',transaction_type:'TVOD',current_order_lines:'1000',
        booked_amount_minor:'9007199254740991',booked_amount_decimal:'90071992547409.9100'}],
        playback:[],campaigns:[],counts:[{customers:'700',content:'305'}],
        publication:[{run_id:'actual-gold-publication',completed_at:'2026-10-07T13:00:00Z',order_lines:'1000'}]},
      new Date('2026-10-07T13:30:00Z'));
    expect(result.state).toBe('ready');
    expect(result.commercial[0].booked_amount_minor).toBe('9007199254740991');
    expect(result.freshness.published_at).toBe('2026-10-07T13:00:00.000Z');
    expect(result.dimensions.customers).toBe('700');
  });
});
