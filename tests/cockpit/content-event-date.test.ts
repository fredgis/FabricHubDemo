import{describe,expect,it}from'vitest';
import{contentEventState,releaseDateOnly}from'../../apps/cockpit/tools/lib/content-event.mjs';
describe('canonical future content release-date serialization',()=>{
  it('emits SQL UTC-midnight Date as date only and retains other UTC timestamps',()=>{
    expect(contentEventState({id:'surrogate',content_key:'ACTUAL-FILM',
      release_date:new Date('2010-09-27T00:00:00.000Z'),updated_at:new Date('2026-10-07T13:45:12.345Z')}))
      .toEqual({content_key:'ACTUAL-FILM',release_date:'2010-09-27',updated_at:'2026-10-07T13:45:12.345Z'});
  });
  it('accepts a real calendar date but never silently truncates a non-midnight timestamp',()=>{
    expect(releaseDateOnly('2019-04-04')).toBe('2019-04-04');
    expect(()=>releaseDateOnly('2019-04-04T12:30:00.000Z')).toThrow('UTC midnight');
    expect(()=>releaseDateOnly(new Date('2019-04-04T00:00:00.001Z'))).toThrow('UTC midnight');
    expect(()=>releaseDateOnly('2019-02-30')).toThrow('valid calendar');
  });
});
