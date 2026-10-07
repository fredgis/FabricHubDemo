import { readFile, writeFile } from 'node:fs/promises';
import { RayfinClient } from '@microsoft/rayfin-client';
import { signInWithEntraToken } from '@microsoft/rayfin-auth-provider-fabric';
import { RayfinAuth } from '../node_modules/@microsoft/rayfin-cli/dist/auth/rayfin-auth.js';

const tenant = '11111111-1111-4111-8111-111111111111';
const registry = JSON.parse(await readFile('rayfin/.deployments.json', 'utf8'));
const deployment = registry.deployments[registry.active];
if (deployment.fabricWorkspaceId !== '33333333-3333-4333-8333-333333333333' ||
    deployment.fabricItemId !== '00000000-0000-4000-8000-000000100044') {
  throw new Error('Refusing native invocation outside the recorded MSFlix app.');
}
const auth = new RayfinAuth({ tenantId: tenant });
const cached = await auth.acquireToken(
  ['https://analysis.windows.net/powerbi/api/Item.Execute.All'], { silentOnly: true });
const entraToken = cached.accessToken ?? cached.token;
const claims = JSON.parse(Buffer.from(entraToken.split('.')[1], 'base64url').toString());
if (claims.tid !== tenant || !(claims.scp ?? '').split(' ').includes('Item.Execute.All')) {
  throw new Error('The cached delegated Rayfin identity lacks the required tenant or Execute scope.');
}
const client = new RayfinClient({
  baseUrl: deployment.fabricApiUrl,
  publishableKey: deployment.publishableKey,
  authStorage: false,
});
try {
  const session = await signInWithEntraToken(client.auth, { entraToken });
  if (!session.isAuthenticated) throw new Error('Native delegated app authentication did not complete.');
  const health = await client.functions.health.invoke();
  console.log(JSON.stringify({ function: 'health', result: health }));
  const pages = await client.functions.businessViews.invoke();
  console.log(JSON.stringify({
    function: 'businessViews', state: pages.dashboard.state, source: pages.dashboard.source,
    publication: pages.dashboard.freshness, catalog: pages.catalog.length,
    customers: pages.customers.length, offers: pages.offers.length, orders: pages.orders.length,
  }));
  const graph = await client.functions.businessGraph.invoke();
  const evidence = {
    native_user_authenticated: true, native_health: health, gold: pages.dashboard.freshness,
    graph: { state: graph.state, nodes: graph.nodes.length, edges: graph.edges.length },
    verified_at: new Date().toISOString(),
  };
  if (pages.dashboard.state !== 'ready' || graph.state !== 'ready' || !graph.edges.length) {
    throw new Error('The real native app read surfaces are not all ready.');
  }
  await writeFile('../../.state/cockpit-native-readback.json', JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify(evidence));
} catch (error) {
  console.error(JSON.stringify({ native_verified: false, code: error.code, message: error.message, interactive_login: false }));
  process.exitCode = 1;
} finally {
  client.auth.destroy();
}
