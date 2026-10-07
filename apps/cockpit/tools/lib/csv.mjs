/** Strict RFC-4180-style UTF-8 interchange; no package or spreadsheet execution. */
export function parseCsv(text, maxRows = 100000) {
  text = text.replace(/^\uFEFF/, '');
  const records = [];
  let row = [], field = '', quoted = false, closed = false;
  const pushRow = () => {
    row.push(field);
    if (row.some(value => value !== '')) records.push(row);
    if (records.length > maxRows + 1) throw new Error(`CSV exceeds ${maxRows} records.`);
    row = []; field = ''; closed = false;
  };
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') {
        if (text[i+1] === '"') { field += '"'; i++; }
        else { quoted = false; closed = true; }
      } else field += ch;
    } else if (ch === '"') {
      if (field || closed) throw new Error('Unexpected quote in CSV field.');
      quoted = true;
    } else if (ch === ',') {
      row.push(field); field = ''; closed = false;
    } else if (ch === '\r' || ch === '\n') {
      if (ch === '\r' && text[i+1] === '\n') i++;
      pushRow();
    } else {
      if (closed) throw new Error('Characters follow a closed quoted CSV field.');
      field += ch;
    }
  }
  if (quoted) throw new Error('Unclosed quoted CSV field.');
  if (field || row.length || closed) pushRow();
  if (!records.length) throw new Error('CSV is empty.');
  const headers = records.shift();
  if (headers.some(name => !/^[A-Za-z][A-Za-z0-9_]*$/.test(name)) || new Set(headers).size !== headers.length)
    throw new Error('CSV headers must be nonempty unique identifiers.');
  return records.map((values, i) => {
    if (values.length !== headers.length) throw new Error(`CSV row ${i+2} has an inconsistent number of fields.`);
    return Object.fromEntries(headers.map((header, index) => [header, values[index]]));
  });
}
export function csvText(headers, records) {
  const escape = value => `"${String(value ?? '').replaceAll('"', '""')}"`;
  return headers.join(',') + '\r\n' + records.map(row => headers.map(name => escape(row[name])).join(',')).join('\r\n') + '\r\n';
}
