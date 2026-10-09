export function parseFlixyVerificationAnswer(text) {
  const json = text.trim()
    .replace(/\s+File\(s\) result_\d+\.(?:json|csv)(?:,\s*result_\d+\.(?:json|csv))* were generated as a result of the query\.$/, '')
    .replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '');
  return JSON.parse(json);
}
