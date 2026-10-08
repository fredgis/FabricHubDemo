/** Owned presentation assets only. Never changes canonical catalog or Oracle. */
import{readFile,mkdir,writeFile,stat,rename}from'node:fs/promises';
import{createHash}from'node:crypto';
import{parseArgs}from'node:util';
import{resolve}from'node:path';
import{optimizeArtwork}from'./artwork-optimize.mjs';
import{
  createArtworkClient,commonsImageInfo,normalizedFileTitle,permittedImageLicense,publicSourceUrl,
}from'./artwork-recovery.mjs';
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
let previousItems=[];
try{previousItems=JSON.parse(await readFile('public/artwork-manifest.json','utf8')).items;}
catch(error){if(error.code!=='ENOENT')throw error;}
const previousByKey=new Map(previousItems.map(item=>[item.content_key,item]));
const client=createArtworkClient({maxRequests:120});
let knownSources=[];
try{knownSources=JSON.parse(await readFile('public/artwork/known-sources.json','utf8')).items;}
catch(error){if(error.code!=='ENOENT')throw error;}
const needsRecovery=catalog.some(film=>film.artwork_available!==false&&film.image_url!=='/catalog-unavailable.svg'
  &&previousByKey.get(film.content_key)?.kind!=='licensed-reference');
if(values['download-licensed']&&needsRecovery&&!knownSources.length){
  const known=catalog.filter(film=>film.artwork_available!==false&&film.image_url!=='/catalog-unavailable.svg');
  const commons=await commonsImageInfo(known.filter(film=>film.artwork_source_url?.startsWith('https://commons.wikimedia.org/wiki/File:'))
    .map(film=>film.artwork_source_url),client);
  knownSources=known.map(film=>{
    const source=film.artwork_source_url?commons.get(normalizedFileTitle(film.artwork_source_url)):null;
    if(film.artwork_source_url&&!source)throw new Error(`Commons could not verify an approved image license: ${film.content_key}`);
    return{content_key:film.content_key,expected_title:film.title,expected_year:String(film.release_date).slice(0,4),
      ...(source??{source_url:film.source_url,image_url:publicSourceUrl(film.image_url).href,
        license:film.license,license_url:film.license_url,
        author:'Blender Foundation / Blender Studio',metadata_origin:'Previously verified canonical artwork metadata'})};
  });
  await writeFile('public/artwork/known-sources.json',JSON.stringify({schema_version:1,items:knownSources},null,2),'utf8');
}
const knownByKey=new Map(knownSources.map(source=>[source.content_key,source]));
const sha256=bytes=>createHash('sha256').update(bytes).digest('hex');
async function optionalJson(path,fallback){
  try{return JSON.parse(await readFile(path,'utf8'));}
  catch(error){if(error.code==='ENOENT')return fallback;throw error;}
}
async function atomicWrite(path,contents){
  try{if(await readFile(path,'utf8')===contents)return;}catch(error){if(error.code!=='ENOENT')throw error;}
  await writeFile(`${path}.tmp`,contents,'utf8');
  await rename(`${path}.tmp`,path);
}
const review=await optionalJson('public/artwork/source-review.json',{known:{},selections:{}});
const discovery=await optionalJson('public/artwork/recovery-candidates.json',{films:[]});
const evidenceByKey=new Map(discovery.films.map(film=>[film.content_key,film]));
const selectedByKey=new Map();
for(const [key,selection]of Object.entries(review.selections??{})){
  const film=catalog.find(row=>row.content_key===key);
  const evidence=evidenceByKey.get(key);
  const candidate=evidence?.candidates?.find(row=>row.commons_title===selection.commons_title);
  if(!film||!candidate||evidence.title!==film.title||evidence.year!==String(film.release_date).slice(0,4)
    ||evidence.wikidata.qid!==key.slice(7)||!['film-still','film-poster'].includes(selection.media_kind)
    ||!selection.association_note||!permittedImageLicense(candidate.license)){
    throw new Error(`Approved artwork must match the unchanged film key, title, year and permitted rights: ${key}`);
  }
  selectedByKey.set(key,{...candidate,media_kind:selection.media_kind,
    association_note:selection.association_note,association_evidence_url:evidence.wikidata.source_url,
    association_category_url:evidence.association_search?.source_url});
}
const inventoryPath='public/artwork/source-inventory.json';
const inventory=await optionalJson(inventoryPath,{schema_version:1,items:[]});
const inventoryByPath=new Map(inventory.items.map(item=>[item.imagepath,item]));
async function retain(item){
  if(item.kind!=='licensed-reference')return;
  inventoryByPath.set(item.imagepath,{...item});
}
async function saveInventory(){
  await atomicWrite(inventoryPath,JSON.stringify({
    schema_version:1,
    notice:'Licensed local source files, including retained references NOT eligible as film imagery. The primary manifest determines presentation.',
    items:[...inventoryByPath.values()],
  },null,2));
}
const sameSource=(left,right)=>Boolean(left&&right&&normalizedFileTitle(left)===normalizedFileTitle(right));
function rasterExtension(bytes){
  if(bytes[0]===0xff&&bytes[1]===0xd8)return'jpg';
  if(bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])))return'png';
  if(bytes.subarray(0,4).toString()==='RIFF'&&bytes.subarray(8,12).toString()==='WEBP')return'webp';
  if(['GIF87a','GIF89a'].includes(bytes.subarray(0,6).toString()))return'gif';
  throw new Error('Response is not a supported raster image.');
}
async function verifyCached(cached,hash){
  if(cached?.kind!=='licensed-reference'||
    !new RegExp(`^/artwork/${hash}-licensed(?:-[a-f0-9]{12})?\\.(jpg|png|webp|gif)$`).test(cached.imagepath))return null;
  try{
    const bytes=await readFile(resolve('public',cached.imagepath.slice(1)));
    if(bytes.length>10*1024*1024||!bytes.length||!cached.imagepath.endsWith(`.${rasterExtension(bytes)}`)||
      sha256(bytes)!==cached.asset_sha256)return null;
    return cached;
  }catch{return null;}
}
function sourceDetails(source){
  return{license_url:source.license_url,author:source.author,download_url:source.image_url,
    license_evidence_url:source.license_evidence_url??source.source_url,
    media_kind:source.media_kind??'licensed-reference',modifications:source.modifications??'None; original image bytes cached locally.',
    association_note:source.association_note,association_evidence_url:source.association_evidence_url,
    association_category_url:source.association_category_url};
}
async function describeKnownCache(cached,source,film,sourceReview){
  const bytes=await readFile(resolve('public',cached.imagepath.slice(1)));
  const original=source.source_sha1&&createHash('sha1').update(bytes).digest('hex')===source.source_sha1;
  const modifications=original?'None; original Commons image bytes cached locally.':
    source.source_sha1?'Previously cached official Commons raster thumbnail retained byte-for-byte; no new edits.':
      'Previously cached provider image retained byte-for-byte; no new edits.';
  return{...cached,...sourceDetails({...source,
    image_url:publicSourceUrl(original?(source.original_url??source.image_url):film.image_url).href,
    modifications,media_kind:sourceReview?.media_kind,association_note:sourceReview?.association_note,
  }),eligible_as_film_primary:sourceReview?.eligible!==false};
}
const manifest=[];let downloaded=0;let reused=0;const failures=[];
for(const film of catalog){
  if(typeof film.content_key!=='string'||typeof film.title!=='string')throw new Error('Invalid canonical film identity.');
  const hash=sha256(film.content_key).slice(0,20);
  const editorialPath=`/artwork/${hash}-editorial.svg`;
  const fallback=editorial(film,hash);
  await atomicWrite(resolve('public',editorialPath.slice(1)),fallback);
  const item={content_key:film.content_key,title:film.title,imagepath:editorialPath,fallback_path:editorialPath,
    kind:'original-editorial',license:'MSFlix original editorial illustration; demo use',
    attribution:'Original editorial graphic created for MSFlix. Not official film artwork and not a licensed movie poster.',
    alt:`Illustration MSFlix for ${film.title}; not an official film poster`,
    source_url:null,canonical_artwork_available:film.artwork_available!==false&&film.image_url!=='/catalog-unavailable.svg',
    media_kind:'editorial-placeholder',author:'MSFlix',asset_sha256:sha256(fallback)};
  const known=knownByKey.get(film.content_key);
  const knownReview=review.known?.[film.content_key];
  const selected=selectedByKey.get(film.content_key);
  const source=selected??(knownReview?.eligible===false?null:known?{
    ...known,media_kind:knownReview?.media_kind,association_note:knownReview?.association_note,
  }:null);
  let previous=await verifyCached(previousByKey.get(film.content_key),hash);
  // Original source metadata must not relabel an older thumbnail as original-resolution bytes.
  if(known){
    for(const archived of inventoryByPath.values()){
      if(archived.content_key!==film.content_key||!sameSource(archived.source_url,known.source_url))continue;
      const verified=await verifyCached(archived,hash);
      if(!verified)continue;
      const described=await describeKnownCache(verified,known,film,knownReview);
      inventoryByPath.set(described.imagepath,described);
      if(previous?.imagepath===described.imagepath)previous=described;
    }
    if(previous&&sameSource(previous.source_url,known.source_url)){
      previous=await describeKnownCache(previous,known,film,knownReview);
    }
  }
  if(previous)await retain(previous); // Keep even rejected portraits/scenery as explicitly archived references.
  const excluded=previous&&knownReview?.eligible===false&&sameSource(previous.source_url,known?.source_url);
  let cached=excluded?null:previous;
  if(source&&!sameSource(cached?.source_url,source.source_url)){
    for(const archived of inventoryByPath.values()){
      if(archived.content_key===film.content_key&&sameSource(archived.source_url,source.source_url)){
        const verified=await verifyCached(archived,hash);
        if(verified){cached=verified;break;}
      }
    }
  }
  if(cached){
    Object.assign(item,cached,{media_kind:cached.media_kind??'licensed-reference'});
    const actualSource=sameSource(cached.source_url,source?.source_url)?source:
      sameSource(cached.source_url,known?.source_url)?{...known,media_kind:knownReview?.media_kind,
        association_note:knownReview?.association_note}:null;
    if(actualSource)Object.assign(item,sourceDetails(actualSource),{
      download_url:cached.download_url??actualSource.image_url,
      modifications:cached.modifications??actualSource.modifications,
    });
  }
  const needsDownload=source?!sameSource(cached?.source_url,source.source_url):
    !cached&&item.canonical_artwork_available&&knownReview?.eligible!==false;
  let downloadedThisFilm=false;
  if(needsDownload&&values['download-licensed']){
    try{
      const license=source?.license??film.artwork_license??film.license;
      if(!permittedImageLicense(license))throw new Error('Image rights are not an approved CC BY/CC BY-SA/CC0/public-domain license.');
      const url=publicSourceUrl(source?.image_url??film.image_url);
      const bytes=await client.bytes(url.href);
      if(bytes.length<100||bytes.length>10*1024*1024)throw new Error('Unexpected image size.');
      const extension=rasterExtension(bytes);
      if(source?.source_sha1&&source.image_url===source.original_url
        &&createHash('sha1').update(bytes).digest('hex')!==source.source_sha1){
        throw new Error('Downloaded original does not match the official Commons source hash.');
      }
      // A better source gets its own path: never overwrite a good prior licensed file.
      const path=`/artwork/${hash}-licensed${selected?`-${sha256(source.source_url).slice(0,12)}`:''}.${extension}`;
      await writeFile(resolve('public',path.slice(1)),bytes);
      Object.assign(item,{imagepath:path,kind:'licensed-reference',license,
        attribution:selected?`${source.author}. ${source.license}. ${source.commons_title}. ${source.modifications}`:film.attribution,
        alt:selected?`${source.media_kind==='film-poster'?'Film poster':'Film still'} for ${film.title} (${String(film.release_date).slice(0,4)})`:
          `Licensed reference image associated with ${film.title}`,
        source_url:source?.source_url??film.artwork_source_url??film.source_url,
        license_url:source?.license_url??film.artwork_license_url??film.license_url,
        author:source?.author??film.artwork_author,download_url:url.href,
        license_evidence_url:source?.license_evidence_url??source?.source_url??film.source_url,
        asset_sha256:sha256(bytes)});
      if(source)Object.assign(item,sourceDetails(source));
      downloaded++;downloadedThisFilm=true;
      await retain(item);await saveInventory();
    }catch(error){failures.push({content_key:film.content_key,error:String(error.message)});}
  }
  if(cached&&!downloadedThisFilm)reused++;
  if(item.kind==='original-editorial'){
    item.artwork_unavailable_reason=knownReview?.eligible===false?knownReview.association_note:
      'No approved film still or poster found in the bounded licensed-source pass; rights-cleared film artwork is required.';
  }
  if(item.media_kind==='film-title-graphic')item.alt=`Film title graphic for ${film.title}; not a film still`;
  if(item.media_kind==='film-publicity')item.alt=`Film publicity photograph for ${film.title}; not a frame from the film`;
  // Presentation titles are always the intact canonical strings, never console/SQL output.
  item.title=film.title;
  await retain(item);
  manifest.push(item);
}
if(new Set(manifest.map(item=>item.content_key)).size!==305||new Set(manifest.map(item=>item.fallback_path)).size!==305)
  throw new Error('Artwork identities or originals are not unique.');
for(const item of manifest)await stat(resolve('public',item.imagepath.slice(1)));
await saveInventory();
await atomicWrite('public/artwork-manifest.json',JSON.stringify({schema_version:1,generated_at:new Date().toISOString(),items:manifest},null,2));
await atomicWrite('src/assets/catalog-art.generated.ts',
  `// Generated owned presentation manifest. No canonical metadata or rights are changed.\nexport const catalogArt = ${JSON.stringify(manifest)} as const;\n`);
await optimizeArtwork();
console.log(JSON.stringify({film_presentations:305,unique_original_fallbacks:305,licensed_local_images:downloaded+reused,
  reused_licensed_images:reused,downloaded_licensed_images:downloaded,
  original_primary:305-downloaded-reused,failed_licensed_cache:failures,manifest:'public/artwork-manifest.json',
  primary_media:manifest.reduce((counts,item)=>{counts[item.media_kind]=(counts[item.media_kind]??0)+1;return counts;},{}),
  retained_licensed_source_files:inventoryByPath.size,
  all_local_files_verified:true,no_canonical_data_modified:true}));
