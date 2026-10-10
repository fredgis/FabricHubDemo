import { useCallback, useEffect, useRef, useState } from 'react';
import { loadSnapshot, safeError, type OperationalScope, type Snapshot } from '@/services/business';
import { loadGoldViews } from '@/services/goldViews';
import type { GoldView } from '../../rayfin/functions/src/gold-pages';

type GoldResult = Awaited<ReturnType<typeof loadGoldViews>>;
type CachedGold = { result: GoldResult; readAt: number };
type CachedOperational = { snapshot: Snapshot; updated: Date };
const goldSections = new Set(['overview', 'catalog', 'audiences', 'demo']);
const operationalSections = new Set(['orders', 'demo', 'operations']);

export function useCockpitReads(section: string) {
  const view = goldSections.has(section) ? section as GoldView : undefined;
  const scope = operationalSections.has(section) ? section as OperationalScope : undefined;
  const [snapshots, setSnapshots] = useState<Partial<Record<OperationalScope, CachedOperational>>>({});
  const [operationalPending, setOperationalPending] = useState<Partial<Record<OperationalScope, boolean>>>({});
  const [operationalErrors, setOperationalErrors] = useState<Partial<Record<OperationalScope, string>>>({});
  const [pages, setPages] = useState<Partial<Record<GoldView, CachedGold>>>({});
  const [pending, setPending] = useState<Partial<Record<GoldView, boolean>>>({});
  const [errors, setErrors] = useState<Partial<Record<GoldView, string>>>({});
  const cache = useRef<Partial<Record<GoldView, CachedGold>>>({});
  const requests = useRef(new Map<GoldView, Promise<void>>());
  const operational = useRef<Partial<Record<OperationalScope, { readAt?: number; request?: Promise<void> }>>>({});
  const selected = useRef({ view, scope });
  selected.current = { view, scope };
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const readOperational = useCallback((scope: OperationalScope): Promise<void> => {
    const existing = operational.current[scope]?.request;
    if (existing) return existing;
    setOperationalPending(old => ({ ...old, [scope]: true }));
    setOperationalErrors(old => ({ ...old, [scope]: '' }));
    const request = loadSnapshot(scope).then(value => {
      const entry = operational.current[scope];
      if (!mounted.current || entry?.request !== request) return;
      const readAt = Date.now();
      entry.readAt = readAt;
      setSnapshots(old => ({ ...old, [scope]: { snapshot: value, updated: new Date(readAt) } }));
    }).catch(failure => {
      if (mounted.current && operational.current[scope]?.request === request)
        setOperationalErrors(old => ({ ...old, [scope]: safeError(failure) }));
    }).finally(() => {
      const entry = operational.current[scope];
      if (entry?.request !== request) return;
      entry.request = undefined;
      if (mounted.current) setOperationalPending(old => ({ ...old, [scope]: false }));
    });
    operational.current[scope] = { ...operational.current[scope], request };
    return request;
  }, []);

  const readGold = useCallback((scope: GoldView): Promise<void> => {
    const existing = requests.current.get(scope);
    if (existing) return existing;
    setPending(old => ({ ...old, [scope]: true }));
    setErrors(old => ({ ...old, [scope]: '' }));
    const request = loadGoldViews(scope).then(result => {
      if (!mounted.current) return;
      const entry = { result, readAt: Date.now() };
      cache.current[scope] = entry;
      setPages(old => ({ ...old, [scope]: entry }));
    }).catch(failure => {
      if (mounted.current) setErrors(old => ({ ...old, [scope]: safeError(failure) }));
    }).finally(() => {
      requests.current.delete(scope);
      if (mounted.current) setPending(old => ({ ...old, [scope]: false }));
    });
    requests.current.set(scope, request);
    return request;
  }, []);

  useEffect(() => {
    if (view && Date.now() - (cache.current[view]?.readAt ?? 0) > 30000) void readGold(view);
    const entry = scope ? operational.current[scope] : undefined;
    if (scope && (entry?.readAt === undefined || Date.now() - entry.readAt > 30000)) void readOperational(scope);
  }, [view, scope, readGold, readOperational]);

  const refresh = useCallback(async () => {
    const { view, scope } = selected.current;
    // Commands may finish after navigation. Invalidate every scope, including pre-command reads.
    operational.current = {};
    setOperationalPending({});
    await Promise.all([
      ...(view ? [readGold(view)] : []),
      ...(scope ? [readOperational(scope)] : []),
    ]);
  }, [readGold, readOperational]);

  const snapshot = scope ? snapshots[scope]?.snapshot ?? null : null;
  const error = scope ? operationalErrors[scope] ?? '' : '';
  return {
    hasReadGold: Object.keys(pages).length > 0,
    snapshot, loading: scope ? Boolean(operationalPending[scope] || (!snapshot && !error)) : false,
    error, updated: scope ? snapshots[scope]?.updated : undefined, refresh,
    gold: view ? pages[view]?.result : undefined,
    goldLoading: view ? Boolean(pending[view] || (!pages[view] && !errors[view])) : false,
    goldError: view ? errors[view] ?? '' : '',
  };
}
