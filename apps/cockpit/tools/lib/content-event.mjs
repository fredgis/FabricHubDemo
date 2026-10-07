/** Calendar-date serialization only for content.release_date; never for event timestamps. */
export function releaseDateOnly(value){
  let iso;
  if(value instanceof Date){
    if(!Number.isFinite(value.getTime()))throw new Error('release_date must be a valid calendar date.');
    iso=value.toISOString();
  }else if(typeof value==='string'){
    if(/^\d{4}-\d{2}-\d{2}$/.test(value)){
      const parsed=new Date(`${value}T00:00:00.000Z`);
      if(!Number.isFinite(parsed.getTime())||parsed.toISOString().slice(0,10)!==value)
        throw new Error('release_date must be a valid calendar date.');
      return value;
    }
    iso=value;
  }else throw new Error('release_date must be a valid calendar date.');
  if(!/^\d{4}-\d{2}-\d{2}T00:00:00(?:\.0{1,7})?Z$/.test(iso))
    throw new Error('release_date timestamp must be strict UTC midnight; non-midnight values are not truncated.');
  return releaseDateOnly(iso.slice(0,10));
}
export function contentEventState(row){
  const result=Object.fromEntries(Object.entries(row).filter(([name])=>name!=='id')
    .map(([name,value])=>[name,value instanceof Date?value.toISOString():value]));
  result.release_date=releaseDateOnly(row.release_date);
  return result;
}
