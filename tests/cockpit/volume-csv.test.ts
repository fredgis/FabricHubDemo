import { describe, expect, it } from 'vitest';
import { parseCsv, csvText } from '../../apps/cockpit/tools/lib/csv.mjs';
describe('trusted volume CSV interchange', () => {
  it('preserves actual titles, quoted artwork URLs and attribution without corrupting multiline credits', () => {
    const rows = parseCsv('\uFEFFcontent_key,title,attribution\r\nFILM-1,"Story, Part Two","Studio ""A""\nCC BY 4.0"\r\n');
    expect(rows).toEqual([{ content_key: 'FILM-1', title: 'Story, Part Two', attribution: 'Studio "A"\nCC BY 4.0' }]);
    expect(parseCsv(csvText(['content_key','title','attribution'], rows))).toEqual(rows);
  });
});
