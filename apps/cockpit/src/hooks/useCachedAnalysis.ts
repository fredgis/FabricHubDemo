import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useReadCache } from '@/hooks/ReadCacheContext';
import { safeError } from '@/services/business';

type ReadState<Result> = { data: Result | null; loading: boolean; error: string };
type Pending = { key: string; revision: number; promise: Promise<void> };
type Failure = { revision: number; error: string };

function selectionKey(filters: object) {
  return JSON.stringify(Object.fromEntries(Object.entries(filters).sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)));
}

function savedSelection<Filters extends object>(value: unknown): Partial<Filters> {
  return value && typeof value === 'object' && !Array.isArray(value) && Object.values(value).every(item => typeof item === 'string')
    ? value as Partial<Filters>
    : {};
}

export function useCachedAnalysis<Filters extends object, Result extends { filters: Filters }>(
  active: boolean,
  refreshKey: number,
  namespace: 'insights' | 'campaign',
  load: (filters: Partial<Filters>) => Promise<Result>,
) {
  const { cache, revision } = useReadCache();
  const prefix = `read:${namespace}:`;
  const preferenceKey = `ui:${namespace}:selection`;
  const scope = useMemo(() => {
    const filters = savedSelection<Filters>(cache.get(preferenceKey));
    const initial: ReadState<Result> = {
      data: cache.get<Result>(prefix + selectionKey(filters)) ?? null,
      loading: false,
      error: '',
    };
    return { filters, initial, mounted: false, sequence: 0, pending: null as Pending | null, failures: new Map<string, Failure>() };
  }, [cache, prefix, preferenceKey]);
  const [state, setState] = useState(() => ({ ...scope.initial, scope }));
  const lastRefresh = useRef(refreshKey);
  const update = useCallback((next: Partial<ReadState<Result>>) => {
    setState(previous => ({ ...(previous.scope === scope ? previous : { ...scope.initial, scope }), ...next }));
  }, [scope]);

  useEffect(() => {
    scope.mounted = true;
    return () => {
      scope.mounted = false;
      scope.sequence += 1;
      scope.pending = null;
    };
  }, [scope]);

  const apply = useCallback((filters: Partial<Filters>) => {
    const key = prefix + selectionKey(filters);
    const currentRevision = cache.getVersion();
    if (scope.pending?.key === key && scope.pending.revision === currentRevision) return scope.pending.promise;
    scope.filters = filters;
    const current = ++scope.sequence;
    scope.pending = null;
    const accept = (result: Result) => {
      if (!scope.mounted || current !== scope.sequence || cache.get(key) !== result) return;
      const canonicalKey = prefix + selectionKey(result.filters);
      if (canonicalKey !== key) cache.set(canonicalKey, result);
      cache.set(preferenceKey, result.filters);
      scope.filters = result.filters;
      update({ data: result, loading: false, error: '' });
    };
    const cached = cache.get<Result>(key);
    if (cached !== undefined) {
      accept(cached);
      return Promise.resolve();
    }
    const failed = scope.failures.get(key);
    if (failed?.revision === currentRevision) {
      update({ loading: false, error: failed.error });
      return Promise.resolve();
    }
    update({ loading: true, error: '' });
    const promise = cache.load(key, () => load(filters)).then(accept).catch(cause => {
      if (!scope.mounted || current !== scope.sequence || currentRevision !== cache.getVersion()) return;
      const error = safeError(cause);
      scope.failures.set(key, { revision: currentRevision, error });
      update({ error });
    }).finally(() => {
      if (current !== scope.sequence) return;
      scope.pending = null;
      if (scope.mounted) update({ loading: false });
    });
    scope.pending = { key, revision: currentRevision, promise };
    return promise;
  }, [cache, load, preferenceKey, prefix, scope, update]);

  const refresh = useCallback(() => {
    cache.invalidate(prefix);
    return active ? apply(scope.filters) : Promise.resolve();
  }, [active, apply, cache, prefix, scope]);

  useEffect(() => {
    if (refreshKey !== lastRefresh.current) {
      lastRefresh.current = refreshKey;
      void refresh();
    } else if (active) {
      void apply(scope.filters);
    }
  }, [active, apply, refresh, refreshKey, revision, scope]);

  const visible = state.scope === scope ? state : scope.initial;
  return { data: visible.data, loading: visible.loading, error: visible.error, apply, refresh };
}
