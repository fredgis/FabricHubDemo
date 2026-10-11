import { useCallback, useEffect, useRef, useState } from 'react';
import { loadSnapshot, safeError, type OperationalScope, type OrderReferences, type OrdersPaging, type Snapshot } from '@/services/business';
import { loadGoldViews } from '@/services/goldViews';
import { canPrefetch } from '@/services/deferred';
import type { GoldView } from '../../rayfin/functions/src/gold-pages';

type GoldResult = Awaited<ReturnType<typeof loadGoldViews>>;
type CachedGold = { result: GoldResult; readAt: number };
type CachedOperational = { snapshot: Snapshot; updated: Date; key: string };
const operationalKey = (scope: OperationalScope, paging: OrdersPaging) =>
  scope === 'orders' ? `${paging.ordersPage}:${paging.playbackPage}` : scope;
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
  const operational = useRef<Partial<Record<OperationalScope, { key: string; readAt?: number; request?: Promise<void> }>>>({});
  const references = useRef<{ value: OrderReferences; readAt: number } | undefined>(undefined);
  const [orderPages, setOrderPages] = useState<OrdersPaging>({ ordersPage: 1, playbackPage: 1 });
  const { ordersPage, playbackPage } = orderPages;
  const selected = useRef({ view, scope, orderPages });
  selected.current = { view, scope, orderPages };
  const prefetchIntent = useRef<symbol | null>(null);
  const cancelPrefetch = useCallback(() => { prefetchIntent.current = null; }, []);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const readOperational = useCallback((scope: OperationalScope): Promise<void> => {
    if (!mounted.current) return Promise.resolve();
    const paging = selected.current.orderPages;
    const key = operationalKey(scope, paging);
    const existing = operational.current[scope];
    if (existing?.request && existing.key === key) return existing.request;
    const cachedReferences = references.current && Date.now() - references.current.readAt <= 30000
      ? references.current : undefined;
    setOperationalPending(old => ({ ...old, [scope]: true }));
    setOperationalErrors(old => ({ ...old, [scope]: '' }));
    const read = scope === 'orders'
      ? loadSnapshot(scope, { ...paging, ...(cachedReferences ? { references: cachedReferences.value } : {}) })
      : loadSnapshot(scope);
    const request = read.then(value => {
      const entry = operational.current[scope];
      if (!mounted.current || entry?.request !== request) return;
      const readAt = Date.now();
      entry.readAt = readAt;
      if (scope === 'orders') {
        if (!cachedReferences) references.current = {
          value: { content: value.content, customers: value.customers, offers: value.offers }, readAt,
        };
        if (value.pagination) {
          const actual = { ordersPage: value.pagination.orders.page, playbackPage: value.pagination.sessions.page };
          entry.key = operationalKey(scope, actual);
          setOrderPages(current => operationalKey(scope, current) === key ? actual : current);
        }
      }
      setSnapshots(old => ({ ...old, [scope]: { snapshot: value, updated: new Date(readAt), key: entry.key } }));
    }).catch(failure => {
      if (mounted.current && operational.current[scope]?.request === request)
        setOperationalErrors(old => ({ ...old, [scope]: safeError(failure) }));
    }).finally(() => {
      const entry = operational.current[scope];
      if (entry?.request !== request) return;
      entry.request = undefined;
      if (mounted.current) setOperationalPending(old => ({ ...old, [scope]: false }));
    });
    operational.current[scope] = { key, request };
    return request;
  }, []);

  const readGold = useCallback((scope: GoldView): Promise<void> => {
    if (!mounted.current) return Promise.resolve();
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

  const prefetch = useCallback(async (next: GoldView) => {
    if (!['catalog', 'audiences'].includes(next) || next === selected.current.view || !canPrefetch()) return;
    const intent = Symbol(next);
    prefetchIntent.current = intent;
    await Promise.all([...requests.current.values(), ...Object.values(operational.current).map(entry => entry.request)]);
    if (!mounted.current || prefetchIntent.current !== intent || !canPrefetch()) return;
    const entry = cache.current[next];
    if (!entry || Date.now() - entry.readAt > 30000) await readGold(next);
  }, [readGold]);

  useEffect(() => {
    cancelPrefetch();
    if (view && Date.now() - (cache.current[view]?.readAt ?? 0) > 30000) void readGold(view);
    const entry = scope ? operational.current[scope] : undefined;
    if (scope && (entry?.key !== operationalKey(scope, { ordersPage, playbackPage })
      || entry?.readAt === undefined || Date.now() - entry.readAt > 30000)) void readOperational(scope);
  }, [view, scope, ordersPage, playbackPage, readGold, readOperational, cancelPrefetch]);

  const refresh = useCallback(async () => {
    if (!mounted.current) return;
    cancelPrefetch();
    const { view, scope } = selected.current;
    // Commands may finish after navigation. Invalidate every scope, including pre-command reads.
    operational.current = {};
    references.current = undefined;
    setOperationalPending({});
    await Promise.all([
      ...(view ? [readGold(view)] : []),
      ...(scope ? [readOperational(scope)] : []),
    ]);
  }, [readGold, readOperational, cancelPrefetch]);

  const snapshot = scope ? snapshots[scope]?.snapshot ?? null : null;
  const error = scope ? operationalErrors[scope] ?? '' : '';
  return {
    hasReadGold: Object.keys(pages).length > 0,
    snapshot, loading: scope ? Boolean(operationalPending[scope]
      || (!error && (!snapshot || snapshots[scope]?.key !== operationalKey(scope, orderPages)))) : false,
    error, updated: scope ? snapshots[scope]?.updated : undefined,
    refresh, prefetch, cancelPrefetch, setOrderPages,
    gold: view ? pages[view]?.result : undefined,
    goldLoading: view ? Boolean(pending[view] || (!pages[view] && !errors[view])) : false,
    goldError: view ? errors[view] ?? '' : '',
  };
}
