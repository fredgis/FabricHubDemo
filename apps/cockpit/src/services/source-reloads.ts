import type { AppSchema } from '../../rayfin/data/schema';
import type { AppFunctionsSchema } from '../../rayfin/functions/src/types';
import { getRayfinClient } from './rayfinClient';

type ControlInput = AppFunctionsSchema['requestControl']['input']['input'];
export type ReloadType = Extract<ControlInput['type'], 'reload_oracle' | 'reload_salesforce'>;
export type ReloadInput = ControlInput & { type: ReloadType; limit: 1 };
export type ReloadCommand = Pick<AppSchema['ControlCommand'],
  'id' | 'idempotency_key' | 'type' | 'status' | 'requested_at' | 'completed_at' | 'error'> & { type: ReloadType };

export const reloadSources = [
  { type: 'reload_oracle', name: 'Oracle' },
  { type: 'reload_salesforce', name: 'Salesforce' },
] as const;
const retryStorageKey = 'msflix.source-reload.retry.v1';

export function isReloadType(type: string): type is ReloadType {
  return type === 'reload_oracle' || type === 'reload_salesforce';
}
export function reloadBlocks(command: ReloadCommand): boolean {
  return ['requested', 'running', 'blocked'].includes(command.status);
}

/** Keep the latest request per source and any older request that still holds the shared lock. */
export function selectReloadCommands(commands: Pick<AppSchema['ControlCommand'], keyof ReloadCommand>[]): ReloadCommand[] {
  const sourceRows = commands.filter((row): row is ReloadCommand => isReloadType(row.type))
    .sort((a, b) => new Date(b.requested_at).getTime() - new Date(a.requested_at).getTime());
  const latest = reloadSources.flatMap(source => sourceRows.find(row => row.type === source.type) ?? []);
  const blocking = sourceRows.find(reloadBlocks);
  return [...new Map([...latest, ...(blocking ? [blocking] : [])].map(row => [row.id, row])).values()];
}

/** Bounded status reads only; no Gold, pipeline or command invocation is performed here. */
export async function readSourceReloads(retryKey?: string): Promise<ReloadCommand[]> {
  const data = getRayfinClient().data.ControlCommand;
  const select = () => data.select(['id', 'idempotency_key', 'type', 'status', 'requested_at', 'completed_at', 'error']);
  const results = await Promise.all([
    ...reloadSources.map(source => select().where({ type: { eq: source.type } })
      .orderBy({ requested_at: 'desc', id: 'desc' }).first(1).execute()),
    select().where({ and: [
      { or: reloadSources.map(source => ({ type: { eq: source.type } })) },
      { or: ['requested', 'running', 'blocked'].map(status => ({ status: { eq: status } })) },
    ] }).orderBy({ requested_at: 'desc', id: 'desc' }).first(1).execute(),
    ...(retryKey ? [select().where({ idempotency_key: { eq: retryKey } }).first(1).execute()] : []),
  ]);
  const rows = results.flat().filter((row): row is AppSchema['ControlCommand'] & { type: ReloadType } => isReloadType(row.type));
  return [...new Map(rows.map(row => [row.id, row])).values()];
}

export function restoreReloadRetry(): ReloadInput | undefined {
  const stored = sessionStorage.getItem(retryStorageKey);
  if (!stored) return undefined;
  const input: unknown = JSON.parse(stored);
  if (!input || typeof input !== 'object' || !('type' in input) || typeof input.type !== 'string'
    || !isReloadType(input.type) || !('limit' in input) || input.limit !== 1
    || !('idempotency_key' in input) || typeof input.idempotency_key !== 'string'
    || !/^[a-zA-Z0-9_:./-]{1,128}$/.test(input.idempotency_key))
    throw new Error('The saved reload retry key is invalid. Ask an operator to check persisted requests before clearing this tab storage.');
  return { type: input.type, limit: 1, idempotency_key: input.idempotency_key };
}

export function retainReloadRetry(input: ReloadInput): void {
  // Persist before invoking: a page reload or lost response must not mint a second command key.
  sessionStorage.setItem(retryStorageKey, JSON.stringify(input));
}
export function clearReloadRetry(): void {
  sessionStorage.removeItem(retryStorageKey);
}
