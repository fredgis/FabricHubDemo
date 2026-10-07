/** Full Rayfin up, guarded against an unrelated workspace/capacity target. */
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { parseArgs } from 'node:util';
import { dirname, resolve } from 'node:path';
import { spawn } from 'node:child_process';
const require = createRequire(new URL('../rayfin/functions/package.json', import.meta.url));
const { DefaultAzureCredential } = require('@azure/identity');
const { values } = parseArgs({ options: { binding: { type: 'string' } } });
if (!values.binding) throw new Error('An exact verified MSFlix binding is required.');
const b = JSON.parse(await readFile(values.binding, 'utf8'));
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
if (!b.verified || !['tenant_id','workspace_id','capacity_id'].every(k => uuid.test(b[k])))
  throw new Error('Refusing an unverified deployment target.');
const credential = new DefaultAzureCredential({ tenantId: b.tenant_id });
const token = await credential.getToken('https://api.fabric.microsoft.com/.default');
const response = await fetch(`https://api.fabric.microsoft.com/v1/workspaces/${b.workspace_id}`, {
  headers: { Authorization: `Bearer ${token.token}`, 'x-ms-fabric-skill': 'rayfin' },
});
if (!response.ok) throw new Error(`Workspace validation failed (HTTP ${response.status}).`);
const workspace = await response.json();
if (workspace.id !== b.workspace_id || workspace.displayName !== 'MSFlix' || workspace.capacityId !== b.capacity_id)
  throw new Error('Refusing deployment: workspace name or approved capacity does not match.');
const cliPackage = resolve('node_modules/@microsoft/rayfin-cli/package.json');
const metadata = JSON.parse(await readFile(cliPackage, 'utf8'));
if (metadata.version !== '1.36.2') throw new Error('Rayfin CLI must remain version-locked at 1.36.2.');
const bin = typeof metadata.bin === 'string' ? metadata.bin : metadata.bin.rayfin;
const child = spawn(process.execPath, [resolve(dirname(cliPackage), bin), 'up',
  '--tenant', b.tenant_id, '--workspace-id', b.workspace_id,
  '--item-name', 'MSFlix Business Control', '--yes', '--json'], { stdio:'inherit' });
await new Promise((resolvePromise, reject) => {
  child.on('error', reject);
  child.on('exit', code => code === 0 ? resolvePromise() : reject(new Error(`Rayfin up failed (${code}).`)));
});
