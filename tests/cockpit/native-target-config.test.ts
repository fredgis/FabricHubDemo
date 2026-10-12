// @vitest-environment node
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { describe, expect, it } from 'vitest';

const expectedEnv = {
  COCKPIT_EXPECTED_TENANT_ID: '11111111-1111-4111-8111-111111111111',
  COCKPIT_EXPECTED_WORKSPACE_ID: '22222222-2222-4222-8222-222222222222',
  COCKPIT_EXPECTED_APP_ID: '33333333-3333-4333-8333-333333333333',
};
const deployment = {
  fabricTenantId: expectedEnv.COCKPIT_EXPECTED_TENANT_ID,
  fabricWorkspaceId: expectedEnv.COCKPIT_EXPECTED_WORKSPACE_ID,
  fabricItemId: expectedEnv.COCKPIT_EXPECTED_APP_ID,
};
const published = { workspace_id: expectedEnv.COCKPIT_EXPECTED_WORKSPACE_ID, published: true };
const otherId = '44444444-4444-4444-8444-444444444444';

function preflight(script: string, env: Record<string, string> = expectedEnv,
  actual = deployment, agent = published): Promise<void> {
  const source = readFileSync(new URL(`../../apps/cockpit/tools/${script}`, import.meta.url), 'utf8');
  const authStart = source.indexOf('const auth = new RayfinAuth(');
  if (authStart < 0) throw new Error('Cannot isolate the configuration checks from authentication.');
  // Execute only the pre-auth checks with in-memory inputs, never the live tool or SDK imports.
  const checks = source.slice(0, authStart).replace(/^import [^\r\n]+;\r?\n/gm, '');
  return runInNewContext(`(async () => { ${checks} })()`, {
    process: { cwd: () => '.' },
    parseArgs: () => ({ values: {} }),
    loadEnvironmentVariables: () => new Map(Object.entries(env)),
    readFile: async (file: string) => {
      if (file === 'rayfin/.deployments.json') {
        return JSON.stringify({ active: 'fixture', deployments: { fixture: actual } });
      }
      if (file === '../../.state/flixy/published.json') return JSON.stringify(agent);
      throw new Error('Only in-memory deployment fixtures may be read.');
    },
  });
}

describe.each(['native-readback.mjs', 'verify-flixy.mjs'])('%s private target checks', script => {
  it('accepts the independently configured expected target', async () => {
    await expect(preflight(script)).resolves.toBeUndefined();
  });

  it.each(Object.keys(expectedEnv))('rejects a missing %s before authentication', async key => {
    const env: Record<string, string> = { ...expectedEnv };
    delete env[key];
    await expect(preflight(script, env)).rejects.toThrow(/Configure COCKPIT_EXPECTED/);
  });

  it.each(Object.keys(expectedEnv))('rejects a malformed %s before authentication', async key => {
    await expect(preflight(script, { ...expectedEnv, [key]: 'not-a-uuid' }))
      .rejects.toThrow(/Configure COCKPIT_EXPECTED/);
  });

  it.each(['fabricWorkspaceId', 'fabricItemId'])('rejects a different deployment %s', async key => {
    await expect(preflight(script, expectedEnv, { ...deployment, [key]: otherId }))
      .rejects.toThrow(/Refusing/);
  });

  it('rejects matching observed records when both drift from the pinned workspace', async () => {
    await expect(preflight(script, expectedEnv,
      { ...deployment, fabricWorkspaceId: otherId }, { ...published, workspace_id: otherId }))
      .rejects.toThrow(/Refusing/);
  });

  it('does not substitute auto-generated deployment values for the independent pins', async () => {
    await expect(preflight(script, {
      RAYFIN_PUBLIC_TENANT_ID: deployment.fabricTenantId,
      RAYFIN_PUBLIC_WORKSPACE_ID: deployment.fabricWorkspaceId,
      RAYFIN_PUBLIC_ITEM_ID: deployment.fabricItemId,
    })).rejects.toThrow(/Configure COCKPIT_EXPECTED/);
  });
});

describe('verify-flixy.mjs published agent checks', () => {
  it('rejects an agent from a different workspace', async () => {
    await expect(preflight('verify-flixy.mjs', expectedEnv, deployment,
      { ...published, workspace_id: otherId })).rejects.toThrow(/Refusing/);
  });

  it('rejects an unpublished agent', async () => {
    await expect(preflight('verify-flixy.mjs', expectedEnv, deployment,
      { ...published, published: false })).rejects.toThrow(/Refusing/);
  });
});
