import type { Health } from '../../rayfin/functions/src/domain';
import { getRayfinClient } from './rayfinClient';
import { createReadCache, type ReadCache } from './readCache';

export type HealthRead = { health: Health; checkedAt: number };
export type HealthReader = (force?: boolean) => Promise<HealthRead>;

export function createHealthReader(cache: ReadCache = createReadCache()): HealthReader {
  let pending: { revision: number; promise: Promise<HealthRead> } | undefined;
  return (force = false) => {
    if (pending?.revision === cache.getVersion()) return pending.promise;
    if (force) cache.invalidate('read:health');
    const promise = cache.load('read:health', async (): Promise<HealthRead> => ({
      health: await getRayfinClient().functions.health.invoke(), checkedAt: Date.now(),
    })).finally(() => { if (pending?.promise === promise) pending = undefined; });
    pending = { revision: cache.getVersion(), promise };
    return promise;
  };
}
