/** Owned presentation assets only. Never changes canonical catalog or Oracle. */
import{readFile,mkdir,writeFile,stat}from'node:fs/promises';
import{createHash}from'node:crypto';
import{parseArgs}from'node:util';
import{resolve}from'node:path';
const{values}=parseArgs({options:{catalog:{type:'string',default:'../../data/catalog.json'},
  'download-licensed':{type:'boolean'}}});
const catalog=JSON.parse(await readFile(values.catalog,'utf8'));
if(!Array.isArray(catalog)||catalog.length!==305)throw new Error('Expected exact 305-film canonical catalog for this asset pass.');
await mkdir('public/artwork',{recursive:true});await mkdir('src/assets',{recursive:true});
const xml=text=>String(text).replace(/[<>&"']/g,ch=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&apos;'}[ch]));
function editorial(film,hash){
  const words=film.title.split(/\s+/);const lines=[];let line='';
  for(const word of words){if((line+' '+word).length>25&&line){lines.push(line);line=word;}else line=(line+' '+word).trim();}
  if(line)lines.push(line);
  const layouts=[
    `<circle cx="745" cy="210" r="220" fill="#ed6757" opacity=".72"/><circle cx="745" cy="210" r="152" fill="#121315"/><rect x="594" y="30" width="3" height="400" fill="#f1f0ee" opacity=".4"/>`,
    `<path d="M490 600L870 0H1040L660 600Z" fill="#ed6757" opacity=".65"/><path d="M580 600L960 0" stroke="#f1f0ee" stroke-width="2" opacity=".55"/>`,
    `<rect x="560" y="64" width="315" height="385" fill="#34353a"/><rect x="610" y="105" width="235" height="270" fill="#ed6757" opacity=".75"/><circle cx="723" cy="220" r="85" fill="#1b1c1f"/>`,
    `<circle cx="736" cy="245" r="196" fill="none" stroke="#ed6757" stroke-width="65"/><path d="M515 70L924 465" stroke="#f1f0ee" stroke-width="3" opacity=".6"/>`,
    `<path d="M535 90H880V435H535Z M590 145H825V380H590Z" fill="#ed6757" fill-rule="evenodd" opacity=".6"/><path d="M655 75V450M535 265H880" stroke="#b2b1b5" stroke-width="2"/>`,
  ];
  const motif=layouts[parseInt(hash.slice(0,2),16)%layouts.length];
  const position=140+parseInt(hash.slice(2,4),16)%130;
  const top=Math.max(250,430-lines.length*53);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 600"><title>${xml(film.title)}: original MSFlix editorial illustration, not official artwork</title>
    <rect width="960" height="600" fill="#1b1c1f"/>${motif}<path d="M0 ${position}L960 ${position+150}" stroke="#b2b1b5" opacity=".12"/>
    <rect x="0" y="0" width="520" height="600" fill="#121315" opacity=".88"/>
    <text x="42" y="65" fill="#ed6757" font-family="Segoe UI,Arial,sans-serif" font-size="19" font-weight="700" letter-spacing="4">MSFLIX</text>
    <text x="44" y="112" fill="#b2b1b5" font-family="Segoe UI,Arial,sans-serif" font-size="14">${xml(String(film.release_date).slice(0,4))} / ${xml(film.genre)}</text>
    ${lines.map((text,i)=>`<text x="42" y="${top+i*53}" fill="#f1f0ee" font-family="Segoe UI,Arial,sans-serif" font-size="${text.length>25?32:42}" font-weight="650">${xml(text)}</text>`).join('')}
    <text x="44" y="558" fill="#b2b1b5" font-family="Segoe UI,Arial,sans-serif" font-size="13">Illustration MSFlix · Not an official film poster</text></svg>`;
}
const manifest=[];let downloaded=0;const failures=[];
for(const film of catalog){
  if(typeof film.content_key!=='string'||typeof film.title!=='string')throw new Error('Invalid canonical film identity.');
  const hash=createHash('sha256').update(film.content_key).digest('hex').slice(0,20);
  const editorialPath=`/artwork/${hash}-editorial.svg`;
  await writeFile(resolve('public',editorialPath.slice(1)),editorial(film,hash),'utf8');
  const item={content_key:film.content_key,title:film.title,imagepath:editorialPath,fallback_path:editorialPath,
    kind:'original-editorial',license:'MSFlix original editorial illustration; demo use',
    attribution:'Original editorial graphic created for MSFlix. Not official film artwork and not a licensed movie poster.',
    alt:`Illustration MSFlix for ${film.title}; not an official film poster`,
    source_url:null,canonical_artwork_available:film.artwork_available!==false&&film.image_url!=='/catalog-unavailable.svg'};
  if(item.canonical_artwork_available&&values['download-licensed']){
    try{
      const url=new URL(film.image_url);
      if(url.protocol!=='https:'||!['studio.blender.org','thumb.wikimedia.org','upload.wikimedia.org'].includes(url.hostname))
        throw new Error('Asset host is not in the verified-source allow-list.');
      const response=await fetch(url,{signal:AbortSignal.timeout(15000),headers:{'User-Agent':'MSFlixDemo/1.0 licensed reference asset cache'}});
      if(!response.ok)throw new Error(`HTTP ${response.status}`);
      const bytes=Buffer.from(await response.arrayBuffer());
      if(bytes.length<100||bytes.length>10*1024*1024)throw new Error('Unexpected image size.');
      let extension;
      if(bytes[0]===0xff&&bytes[1]===0xd8)extension='jpg';
      else if(bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])))extension='png';
      else if(bytes.subarray(0,4).toString()==='RIFF'&&bytes.subarray(8,12).toString()==='WEBP')extension='webp';
      else throw new Error('Response is not a supported verified image (HTML/SVG is not accepted as a photograph).');
      const path=`/artwork/${hash}-licensed.${extension}`;
      await writeFile(resolve('public',path.slice(1)),bytes);
      Object.assign(item,{imagepath:path,kind:'licensed-reference',license:film.artwork_license??film.license,
        attribution:film.attribution,alt:`Licensed reference image associated with ${film.title}`,
        source_url:film.artwork_source_url??film.source_url,asset_sha256:createHash('sha256').update(bytes).digest('hex')});
      downloaded++;
    }catch(error){failures.push({content_key:film.content_key,error:String(error.message)});}
    await new Promise(resolve=>setTimeout(resolve,150));
  }
  manifest.push(item);
}
if(new Set(manifest.map(item=>item.content_key)).size!==305||new Set(manifest.map(item=>item.fallback_path)).size!==305)
  throw new Error('Artwork identities or originals are not unique.');
for(const item of manifest)await stat(resolve('public',item.imagepath.slice(1)));
await writeFile('public/artwork-manifest.json',JSON.stringify({schema_version:1,generated_at:new Date().toISOString(),items:manifest},null,2),'utf8');
await writeFile('src/assets/catalog-art.generated.ts',
  `// Generated owned presentation manifest. No canonical metadata or rights are changed.\nexport const catalogArt = ${JSON.stringify(manifest)} as const;\n`,'utf8');
console.log(JSON.stringify({film_presentations:305,unique_original_fallbacks:305,licensed_local_images:downloaded,
  original_primary:305-downloaded,failed_licensed_cache:failures,manifest:'public/artwork-manifest.json',
  all_local_files_verified:true,no_canonical_data_modified:true}));
