import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { loadSnapshot, safeError, type OperationalScope, type OrderReferences, type OrdersPaging, type Snapshot } from '@/services/business';
import { loadGoldViews } from '@/services/goldViews';
import { canPrefetch } from '@/services/deferred';
import { useReadCache } from '@/hooks/ReadCacheContext';
import type { GoldView } from '../../rayfin/functions/src/gold-pages';

type GoldResult = Awaited<ReturnType<typeof loadGoldViews>>;
type CachedGold = { result: GoldResult; readAt: number };
type CachedOperational = { snapshot: Snapshot; readAt: number; key: string };
type ReadRequest = { revision: number; promise: Promise<void> };
const goldKey = (view: GoldView) => `read:gold:${view}`;
const snapshotKey = (scope: OperationalScope, key: string) => `read:operational:${scope}:${key}`;
const operationalKey = (scope: OperationalScope, paging: OrdersPaging) =>
  scope === 'orders' ? `${paging.ordersPage}:${paging.playbackPage}` : scope;
const goldSections = new Set(['overview', 'catalog', 'audiences', 'demo']);
const operationalSections = new Set(['orders', 'demo', 'operations']);

export function useCockpitReads(section: string) {
  const { cache: store, revision } = useReadCache();
  const view = goldSections.has(section) ? section as GoldView : undefined;
  const scope = operationalSections.has(section) ? section as OperationalScope : undefined;
  const [snapshots, setSnapshots] = useState<Partial<Record<OperationalScope, CachedOperational>>>({});
  const [operationalPending, setOperationalPending] = useState<Partial<Record<OperationalScope, boolean>>>({});
  const [operationalErrors, setOperationalErrors] = useState<Partial<Record<OperationalScope, string>>>({});
  const [pages, setPages] = useState<Partial<Record<GoldView, CachedGold>>>({});
  const [pending, setPending] = useState<Partial<Record<GoldView, boolean>>>({});
  const [errors, setErrors] = useState<Partial<Record<GoldView, string>>>({});
  const requests = useRef(new Map<GoldView, ReadRequest>());
  const operational = useRef<Partial<Record<OperationalScope, ReadRequest & { key: string }>>>({});
  const [orderPages, setOrderPages] = useState<OrdersPaging>(() => {
    const saved = store.get<OrdersPaging>('ui:orders:pages');
    return saved && Number.isSafeInteger(saved.ordersPage) && saved.ordersPage > 0
      && Number.isSafeInteger(saved.playbackPage) && saved.playbackPage > 0
      ? saved : { ordersPage: 1, playbackPage: 1 };
  });
  const { ordersPage, playbackPage } = orderPages;
  const selected = useRef({ view, scope, orderPages });
  selected.current = { view, scope, orderPages };
  const prefetchIntent = useRef<symbol | null>(null);
  const cancelPrefetch = useCallback(() => { prefetchIntent.current = null; }, []);
  const refreshRequest = useRef<{ key: string; promise: Promise<void> } | undefined>(undefined);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => {
    store.set('ui:orders:pages', { ordersPage, playbackPage });
  }, [store, ordersPage, playbackPage]);

  const readOperational = useCallback((scope: OperationalScope): Promise<void> => {
    if (!mounted.current) return Promise.resolve();
    const paging = selected.current.orderPages;
    const key = operationalKey(scope, paging);
    const storageKey = snapshotKey(scope, key);
    const accept = (entry: CachedOperational) => {
      if (scope === 'orders') {
        const value = entry.snapshot;
        store.set<OrderReferences>('read:order-references', {
          content: value.content, customers: value.customers, offers: value.offers,
        });
        if (value.pagination) {
          const actual = { ordersPage: value.pagination.orders.page, playbackPage: value.pagination.sessions.page };
          store.set(snapshotKey(scope, entry.key), entry);
          setOrderPages(current => operationalKey(scope, current) === key && entry.key !== key ? actual : current);
        }
      }
      setSnapshots(old => old[scope] === entry ? old : { ...old, [scope]: entry });
    };
    const cached = store.get<CachedOperational>(storageKey);
    if (cached) {
      delete operational.current[scope];
      accept(cached);
      setOperationalPending(old => ({ ...old, [scope]: false }));
      setOperationalErrors(old => ({ ...old, [scope]: '' }));
      return Promise.resolve();
    }
    const existing = operational.current[scope];
    if (existing?.key === key && existing.revision === store.getVersion()) return existing.promise;
    const cachedReferences = store.get<OrderReferences>('read:order-references');
    setOperationalPending(old => ({ ...old, [scope]: true }));
    setOperationalErrors(old => ({ ...old, [scope]: '' }));
    const read = store.load(storageKey, async (): Promise<CachedOperational> => {
      const value = scope === 'orders'
        ? await loadSnapshot(scope, { ...paging, ...(cachedReferences ? { references: cachedReferences } : {}) })
        : await loadSnapshot(scope);
      const actual = value.pagination
        ? { ordersPage: value.pagination.orders.page, playbackPage: value.pagination.sessions.page } : paging;
      return { snapshot: value, readAt: Date.now(), key: operationalKey(scope, actual) };
    });
    const request = read.then(entry => {
      if (!mounted.current || operational.current[scope]?.promise !== request || store.get(storageKey) !== entry) return;
      accept(entry);
    }).catch(failure => {
      if (mounted.current && operational.current[scope]?.promise === request
        && operational.current[scope]?.revision === store.getVersion())
        setOperationalErrors(old => ({ ...old, [scope]: safeError(failure) }));
    }).finally(() => {
      if (operational.current[scope]?.promise !== request) return;
      delete operational.current[scope];
      if (mounted.current) setOperationalPending(old => ({ ...old, [scope]: false }));
    });
    operational.current[scope] = { key, revision: store.getVersion(), promise: request };
    return request;
  }, [store]);

  const readGold = useCallback((scope: GoldView): Promise<void> => {
    if (!mounted.current) return Promise.resolve();
    const key = goldKey(scope);
    const cached = store.get<CachedGold>(key);
    if (cached) {
      requests.current.delete(scope);
      setPages(old => old[scope] === cached ? old : { ...old, [scope]: cached });
      setPending(old => ({ ...old, [scope]: false }));
      setErrors(old => ({ ...old, [scope]: '' }));
      return Promise.resolve();
    }
    const existing = requests.current.get(scope);
    if (existing?.revision === store.getVersion()) return existing.promise;
    setPending(old => ({ ...old, [scope]: true }));
    setErrors(old => ({ ...old, [scope]: '' }));
    const request = store.load(key, async (): Promise<CachedGold> => ({
      result: await loadGoldViews(scope), readAt: Date.now(),
    })).then(entry => {
      if (!mounted.current || requests.current.get(scope)?.promise !== request || store.get(key) !== entry) return;
      setPages(old => ({ ...old, [scope]: entry }));
    }).catch(failure => {
      if (mounted.current && requests.current.get(scope)?.promise === request
        && requests.current.get(scope)?.revision === store.getVersion())
        setErrors(old => ({ ...old, [scope]: safeError(failure) }));
    }).finally(() => {
      if (requests.current.get(scope)?.promise !== request) return;
      requests.current.delete(scope);
      if (mounted.current) setPending(old => ({ ...old, [scope]: false }));
    });
    requests.current.set(scope, { revision: store.getVersion(), promise: request });
    return request;
  }, [store]);

  const prefetch = useCallback(async (next: GoldView) => {
    if (!['catalog', 'audiences'].includes(next) || next === selected.current.view || !canPrefetch()) return;
    const intent = Symbol(next);
    prefetchIntent.current = intent;
    await Promise.all([...requests.current.values(), ...Object.values(operational.current)].map(entry => entry.promise));
    if (!mounted.current || prefetchIntent.current !== intent || !canPrefetch()) return;
    if (!store.get(goldKey(next))) await readGold(next);
  }, [readGold, store]);

  useEffect(() => {
    cancelPrefetch();
    if (view) void readGold(view);
    if (scope) void readOperational(scope);
  }, [view, scope, ordersPage, playbackPage, revision, readGold, readOperational, cancelPrefetch]);

  const refresh = useCallback((invalidateAll = false): Promise<void> => {
    if (!mounted.current) return Promise.resolve();
    const { view, scope, orderPages } = selected.current;
    const key = `${view}:${scope}:${orderPages.ordersPage}:${orderPages.playbackPage}:${invalidateAll}`;
    if (!invalidateAll && refreshRequest.current?.key === key) return refreshRequest.current.promise;
    cancelPrefetch();
    if (invalidateAll) store.invalidate('read:');
    else {
      if (view) store.invalidate(goldKey(view));
      if (scope) store.invalidate(`read:operational:${scope}:`);
      if (scope === 'orders' || scope === 'demo') store.invalidate('read:order-references');
      if (scope === 'operations') store.invalidate('read:health');
    }
    const promise = Promise.all([
      ...(view ? [readGold(view)] : []),
      ...(scope ? [readOperational(scope)] : []),
    ]).then(() => {}).finally(() => {
      if (refreshRequest.current?.promise === promise) refreshRequest.current = undefined;
    });
    refreshRequest.current = { key, promise };
    return promise;
  }, [readGold, readOperational, cancelPrefetch, store]);

  const cachedSnapshot = scope ? store.get<CachedOperational>(snapshotKey(scope, operationalKey(scope, orderPages))) : undefined;
  const currentSnapshot = cachedSnapshot ?? (scope ? snapshots[scope] : undefined);
  const cachedGold = view ? store.get<CachedGold>(goldKey(view)) : undefined;
  const currentGold = cachedGold ?? (view ? pages[view] : undefined);
  const updated = useMemo(() => currentSnapshot ? new Date(currentSnapshot.readAt) : undefined, [currentSnapshot]);
  const error = scope ? operationalErrors[scope] ?? '' : '';
  return {
    hasReadGold: Boolean(currentGold) || Object.keys(pages).length > 0,
    snapshot: currentSnapshot?.snapshot ?? null,
    loading: scope ? Boolean(operationalPending[scope] || (!error && !cachedSnapshot)) : false,
    error, updated, refresh, prefetch, cancelPrefetch, setOrderPages,
    gold: currentGold?.result,
    goldLoading: view ? Boolean(pending[view] || (!cachedGold && !errors[view])) : false,
    goldError: view ? errors[view] ?? '' : '',
  };
}
