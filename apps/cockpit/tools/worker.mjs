/**
 * Bound backend worker interface. Calls the SAME transaction and commercial
 * handlers as native UDFs, not independent frontend CRUD.
 * The SQL credential is server-side DefaultAzureCredential. Supply an explicit
 * existing OperatorGrants user_id; this entrypoint does not grant permissions.
 */
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { parseArgs } from 'node:util';
import { atomic, poolFor } from '../rayfin/functions/dist/src/storage.js';
import * as commands from '../rayfin/functions/dist/src/commands.js';
import { assertOperator } from '../rayfin/functions/dist/src/domain.js';
const require = createRequire(new URL('../rayfin/functions/package.json', import.meta.url));
const { DefaultAzureCredential } = require('@azure/identity');
const sql = require('mssql');
const { values } = parseArgs({ options: { binding: { type: 'string' }, input: { type: 'string' },
  operation: { type: 'string' }, 'actor-sub': { type: 'string' } } });
if (!values.binding || !values.input || !values['actor-sub'] ||
  !['placeOrder','startPlayback','recordProgress','expireRentals','requestControl'].includes(values.operation))
  throw new Error('Require --binding --input --operation (supported command) --actor-sub (existing authorized worker grant).');
const binding = JSON.parse(await readFile(values.binding, 'utf8'));
const input = JSON.parse(await readFile(values.input, 'utf8'));
const token = await new DefaultAzureCredential({ tenantId: binding.tenant_id }).getToken('https://database.windows.net/.default');
const pool = await poolFor(binding, token.token);
try {
  const result = await pool.request().input('sub', sql.NVarChar(128), values['actor-sub'])
    .query('SELECT id,user_id,enabled,expires_at FROM dbo.OperatorGrants WHERE user_id=@sub');
  const grant = result.recordset[0];
  assertOperator(grant, new Date());
  // A publisher principal only has SELECT/UPDATE published_at and cannot execute
  // commercial writes; database permission is independent of this grant.
  const parameters = values.operation === 'expireRentals' ? {} : input;
  const receipt = await atomic(pool, grant, input.idempotency_key, values.operation, parameters,
    store => commands[values.operation](store, input));
  console.log(JSON.stringify({ actual_persistence: true, receipt }));
} catch (error) {
  console.error(JSON.stringify({ actual_persistence: false, error: error?.code ?? 'COMMAND_FAILED',
    message: error?.code ? 'SQL command failed. Inspect authorized server telemetry.' : String(error?.message).slice(0, 700) }));
  process.exitCode = 1;
} finally { await pool.close(); }
