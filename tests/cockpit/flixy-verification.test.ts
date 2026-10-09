import { describe, expect, it } from 'vitest';
import { parseFlixyVerificationAnswer } from '../../apps/cockpit/tools/flixy-verification.mjs';

const counts = { films: 305, clients: 700 };
const json = JSON.stringify(counts);
const notice = 'File(s) result_0.json were generated as a result of the query.';

describe('Flixy live verification JSON', () => {
  it.each([json, `\`\`\`json\n${json}\n\`\`\``])('preserves plain and fenced JSON parsing', text => {
    expect(parseFlixyVerificationAnswer(text)).toEqual(counts);
  });
  it.each([json, `\`\`\`json\n${json}\n\`\`\``])('accepts the native result-file notice after the answer', text => {
    expect(parseFlixyVerificationAnswer(`${text}\n\n${notice}\n`)).toEqual(counts);
  });
  it('accepts a native notice naming several result files', () => {
    expect(parseFlixyVerificationAnswer(`${json}\n\nFile(s) result_0.json, result_1.csv were generated as a result of the query.`))
      .toEqual(counts);
  });
  it.each([
    `${json}\nUnrelated trailing text.`,
    `Unrelated leading text.\n${json}`,
    `${json}\n${json}`,
    `${json}\nFile(s) https://example.org/result.json were generated as a result of the query.`,
    `invalid JSON\n${notice}`,
  ])('does not hide other invalid JSON output', text => {
    expect(() => parseFlixyVerificationAnswer(text)).toThrow(SyntaxError);
  });
});
