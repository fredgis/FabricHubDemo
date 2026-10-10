import type { Health } from '../../rayfin/functions/src/domain';
import { getRayfinClient } from './rayfinClient';

export type HealthRead = { health: Health; checkedAt: number };
export type HealthReader = (force?: boolean) => Promise<HealthRead>;

/** One in-memory cache per authenticated cockpit, shared across Operations mounts. */
export function createHealthReader(): HealthReader {
  let cached: HealthRead | undefined;
  let pending: Promise<HealthRead> | undefined;

  return (force = false) => {
    if (pending) return pending;
    if (!force && cached && Date.now() - cached.checkedAt < 30_000) return Promise.resolve(cached);

    // A failed recheck must not make the previous success available on the next visit.
    cached = undefined;
    pending = Promise.resolve().then(() => getRayfinClient().functions.health.invoke()).then(health => {
      const result = { health, checkedAt: Date.now() };
      cached = result;
      return result;
    }).finally(() => { pending = undefined; });
    return pending;
  };
}
