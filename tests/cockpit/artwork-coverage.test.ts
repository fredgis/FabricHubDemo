import{describe,expect,it}from'vitest';
import{readFileSync,existsSync,statSync}from'node:fs';
import{resolve}from'node:path';
import{createHash}from'node:crypto';
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
  it('keeps exact canonical keys/titles, valid image hashes, and accurate source credits',()=>{
    const catalog=JSON.parse(readFileSync(resolve('../../data/catalog.json'),'utf8'));
    expect(catalogArt.map(row=>[row.content_key,row.title]))
      .toEqual(catalog.map((row:{content_key:string;title:string})=>[row.content_key,row.title]));
    for(const row of catalogArt){
      const bytes=readFileSync(resolve('public',row.imagepath.slice(1)));
      expect(createHash('sha256').update(bytes).digest('hex')).toBe(row.asset_sha256);
      if(row.kind==='licensed-reference'){
        expect(row.author.length).toBeGreaterThan(0);
        expect(row.license_url).toMatch(/^https?:\/\//);
        expect(new URL(row.source_url).hostname).toMatch(/^(studio\.blender\.org|commons\.wikimedia\.org)$/);
        expect(row.license).not.toMatch(/\b(?:NC|ND)\b|metadata/);
      }
      if(row.media_kind==='film-title-graphic')expect(row.alt).toContain('not a film still');
      if(row.media_kind==='film-publicity')expect(row.alt).toContain('not a frame from the film');
    }
  });
  it('retains all 82 known licensed files, including rejected references, with their actual hashes',()=>{
    const known=JSON.parse(readFileSync(resolve('public/artwork/known-sources.json'),'utf8'));
    const inventory=JSON.parse(readFileSync(resolve('public/artwork/source-inventory.json'),'utf8'));
    expect(known.items).toHaveLength(82);
    for(const source of known.items){
      const keyHash=createHash('sha256').update(source.content_key).digest('hex').slice(0,20);
      const cached=inventory.items.find((row:{content_key:string;imagepath:string})=>
        row.content_key===source.content_key&&row.imagepath.startsWith(`/artwork/${keyHash}-licensed.`));
      expect(cached).toBeDefined();
      const bytes=readFileSync(resolve('public',cached.imagepath.slice(1)));
      expect(bytes.length).toBeLessThanOrEqual(10*1024*1024);
      expect(createHash('sha256').update(bytes).digest('hex')).toBe(cached.asset_sha256);
      if(source.source_sha1&&source.source_sha1!==createHash('sha1').update(bytes).digest('hex')){
        expect(cached.modifications).toContain('thumbnail retained byte-for-byte');
      }
    }
    const hero=catalogArt.find(row=>row.content_key==='MSF-FILM-BUNNY')!;
    expect(hero.imagepath).toBe('/artwork/aed2e74568d1160a0c7c-licensed.webp');
    expect(hero.asset_sha256).toBe('d67a7752c935fdd65fbeeb04a694e85d17265ede562deba535ec4d9a25d44062');
  });
  it('serves smaller verified WebP derivatives without replacing licensed originals',()=>{
    const optimized=JSON.parse(readFileSync(resolve('public/artwork-variants.json'),'utf8'));
    const licensed=catalogArt.filter(row=>row.kind==='licensed-reference');
    expect(optimized.items).toHaveLength(licensed.length);
    let originalBytes=0;let cardBytes=0;
    for(const item of optimized.items){
      const source=licensed.find(row=>row.content_key===item.content_key)!;
      expect(item.source_path).toBe(source.imagepath);
      expect(item.source_sha256).toBe(source.asset_sha256);
      expect(item.license).toBe(source.license);
      expect(item.modifications).toContain('Originals retained unchanged');
      originalBytes+=statSync(resolve('public',source.imagepath.slice(1))).size;
      cardBytes+=item.variants[0].bytes;
      for(const variant of item.variants){
        expect(variant.width).toBeLessThanOrEqual(1200);
        const bytes=readFileSync(resolve('public',variant.path.slice(1)));
        expect(bytes.length).toBe(variant.bytes);
        expect(bytes.toString('ascii',8,12)).toBe('WEBP');
        expect(createHash('sha256').update(bytes).digest('hex')).toBe(variant.sha256);
      }
    }
    expect(cardBytes).toBeLessThan(originalBytes/2);
  });
});
