import { useCallback, useEffect, useRef, useState } from 'react';
import { loadSnapshot, safeError, type Snapshot } from '@/services/business';
import { loadGoldViews } from '@/services/goldViews';
import type { GoldView } from '../../rayfin/functions/src/gold-pages';

type GoldResult = Awaited<ReturnType<typeof loadGoldViews>>;
type CachedGold = { result: GoldResult; readAt: number };
const goldSections = new Set(['overview', 'catalog', 'audiences', 'demo']);
const operationalSections = new Set(['orders', 'demo', 'operations']);

export function useCockpitReads(section: string) {
  const view = goldSections.has(section) ? section as GoldView : undefined;
  const needsOperational = operationalSections.has(section);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [updated, setUpdated] = useState<Date>();
  const [pages, setPages] = useState<Partial<Record<GoldView, CachedGold>>>({});
  const [pending, setPending] = useState<Partial<Record<GoldView, boolean>>>({});
  const [errors, setErrors] = useState<Partial<Record<GoldView, string>>>({});
  const cache = useRef<Partial<Record<GoldView, CachedGold>>>({});
  const requests = useRef(new Map<GoldView, Promise<void>>());
  const operational = useRef<{ readAt: number; request?: Promise<void> }>({ readAt: 0 });
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const readOperational = useCallback((): Promise<void> => {
    if (operational.current.request) return operational.current.request;
    setLoading(true); setError('');
    const request = loadSnapshot().then(value => {
      if (!mounted.current) return;
      operational.current.readAt = Date.now();
      setSnapshot(value); setUpdated(new Date());
    }).catch(failure => {
      if (mounted.current) setError(safeError(failure));
    }).finally(() => {
      operational.current.request = undefined;
      if (mounted.current) setLoading(false);
    });
    operational.current.request = request;
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
    if (needsOperational && Date.now() - operational.current.readAt > 30000) void readOperational();
  }, [view, needsOperational, readGold, readOperational]);

  const refresh = useCallback(async () => {
    await Promise.all([
      ...(view ? [readGold(view)] : []),
      ...(needsOperational ? [readOperational()] : []),
    ]);
  }, [view, needsOperational, readGold, readOperational]);

  return {
    hasReadGold: Object.keys(pages).length > 0,
    snapshot, loading: loading || (needsOperational && !snapshot && !error), error, updated, refresh,
    gold: view ? pages[view]?.result : undefined,
    goldLoading: view ? Boolean(pending[view] || (!pages[view] && !errors[view])) : false,
    goldError: view ? errors[view] ?? '' : '',
  };
}
