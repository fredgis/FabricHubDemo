import type { RuntimeBinding } from '../../apps/cockpit/rayfin/data/schema';

export const operationalBinding: RuntimeBinding = {
  id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', binding_key: 'app-linked-operational', verified: true,
  sql_server: 'fixture.database.fabric.microsoft.com', sql_database: 'fixture-operational',
  fabric_item_id: 'app', workspace_id: 'workspace', capacity_id: 'capacity',
};
export const operationalTables = ['Contents', 'Customers', 'Offers', 'Rentals', 'Playbacks', 'Outboxes',
  'ControlCommands', 'OperatorGrants', 'RuntimeBindings', 'CommandReceipts', 'EventSequences'];

export function operationalToken(identity = 'a', ttl = 3600): string {
  return `header.${Buffer.from(JSON.stringify({ sub: identity, exp: Math.floor(Date.now() / 1000) + ttl }))
    .toString('base64url')}.signature`;
}

export function deferred<T = void>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
