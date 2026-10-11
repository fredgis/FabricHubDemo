import { createContext, useContext, useState, useSyncExternalStore } from 'react';
import { createReadCache, type ReadCache } from '../services/readCache';

export const ReadCacheContext = createContext<ReadCache | undefined>(undefined);

export function useReadCache(): { cache: ReadCache; revision: number } {
  const provided = useContext(ReadCacheContext);
  const [fallback] = useState(() => createReadCache());
  const cache = provided ?? fallback;
  const revision = useSyncExternalStore(cache.subscribe, cache.getVersion, cache.getVersion);
  return { cache, revision };
}
