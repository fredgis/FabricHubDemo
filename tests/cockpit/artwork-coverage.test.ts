import{describe,expect,it}from'vitest';
import{readFileSync,existsSync}from'node:fs';
import{resolve}from'node:path';
import{catalogArt}from'../../apps/cockpit/src/assets/catalog-art.generated';
describe('honest complete local film presentation',()=>{
  it('provides distinct original fallback images and verified local paths for all 305 actual film keys',()=>{
    expect(catalogArt.length).toBe(305);
    expect(new Set(catalogArt.map(row=>row.content_key)).size).toBe(305);
    expect(new Set(catalogArt.map(row=>row.fallback_path)).size).toBe(305);
    for(const row of catalogArt){
      expect(existsSync(resolve('public',row.imagepath.slice(1)))).toBe(true);
      const svg=readFileSync(resolve('public',row.fallback_path.slice(1)),'utf8');
      expect(svg).toContain('Not an official film poster');
      if(row.kind==='original-editorial')expect(row.alt).toContain('not an official film poster');
    }
  });
});
