import { act, cleanup, renderHook } from '@testing-library/react';
import { createElement, type PropsWithChildren } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ReadCacheContext, useReadCache } from '../../apps/cockpit/src/hooks/ReadCacheContext';
import { createReadCache } from '../../apps/cockpit/src/services/readCache';

const scope = JSON.stringify(['https://cockpit.invalid/api', 'workspace-fixture', 'item-fixture', 'user-fixture']);
const value = { rows: [{ id: 'fixture-row' }], count: 1 };

function deferred<T>() {
  let resolve!: (result: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function storedKey(): string {
  const key = localStorage.key(0);
  expect(key).not.toBeNull();
  return key!;
}

beforeEach(() => { localStorage.clear(); });
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  localStorage.clear();
});

describe('manual read-cache persistence', () => {
  it('keeps values for months and across a new cache instance without timers or refetching', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T12:00:00Z'));
    const cache = createReadCache(scope);
    cache.set('insights:overview', value);
    await vi.advanceTimersByTimeAsync(90 * 24 * 60 * 60 * 1000);
    expect(cache.get('insights:overview')).toBe(value);
    const reloaded = createReadCache(scope);
    const retained = reloaded.get('insights:overview');
    const fetcher = vi.fn().mockResolvedValue({ rows: [] });
    expect(retained).toEqual(value);
    expect(await reloaded.load('insights:overview', fetcher)).toBe(retained);
    expect(fetcher).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('persists one versioned entry per key and lazily parses each value only once', () => {
    const cache = createReadCache(scope);
    cache.set('overview', value);
    cache.set('graph', { nodes: [] });
    expect(localStorage.length).toBe(2);
    expect(localStorage.key(0)).toMatch(/^msflix:reads:v1:/);
    expect(localStorage.key(1)).toMatch(/^msflix:reads:v1:/);
    const parse = vi.spyOn(JSON, 'parse');
    const reloaded = createReadCache(scope);
    expect(parse).not.toHaveBeenCalled();
    const retained = reloaded.get('overview');
    expect(reloaded.get('overview')).toBe(retained);
    expect(reloaded.get('overview')).toBe(retained);
    expect(parse).toHaveBeenCalledOnce();
    expect(retained).toEqual(value);
  });

  it.each([null, false, 0, '', [], {}])('retains JSON value %j without treating it as a miss', async item => {
    const cache = createReadCache(scope);
    cache.set('item', item);
    expect(cache.get('item')).toBe(item);
    const reloaded = createReadCache(scope);
    const retained = reloaded.get('item');
    const fetcher = vi.fn().mockResolvedValue('unexpected');
    expect(retained).toEqual(item);
    expect(await reloaded.load('item', fetcher)).toBe(retained);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('isolates application, workspace, item and user scopes', () => {
    const components = JSON.parse(scope) as string[];
    createReadCache(scope).set('overview', value);
    for (let index = 0; index < components.length; index++) {
      const alternate = [...components];
      alternate[index] += '-other';
      const cache = createReadCache(JSON.stringify(alternate));
      expect(cache.get('overview')).toBeUndefined();
      cache.set('overview', { scope: index });
      cache.invalidate();
      expect(createReadCache(scope).get('overview')).toEqual(value);
    }
  });

  it('keeps separator-containing and empty namespaces distinct from each other and memory-only caches', () => {
    createReadCache('a').set('b:overview', 'first');
    createReadCache('a:b').set('overview', 'second');
    createReadCache('').set('overview', 'empty');
    const memory = createReadCache();
    memory.set('overview', 'memory');
    createReadCache('a').invalidate();
    expect(createReadCache('a:b').get('overview')).toBe('second');
    expect(createReadCache('').get('overview')).toBe('empty');
    expect(createReadCache().get('overview')).toBeUndefined();
    expect(memory.get('overview')).toBe('memory');
  });

  it('uses isolated memory without reading, writing or purging browser storage when unscoped', async () => {
    const getItem = vi.spyOn(localStorage, 'getItem');
    const setItem = vi.spyOn(localStorage, 'setItem');
    const removeItem = vi.spyOn(localStorage, 'removeItem');
    const key = vi.spyOn(localStorage, 'key');
    const cache = createReadCache();
    cache.set('overview', value);
    expect(cache.get('overview')).toBe(value);
    expect(createReadCache().get('overview')).toBeUndefined();
    expect(await cache.load('graph', async () => value)).toBe(value);
    cache.invalidate();
    expect(cache.get('overview')).toBeUndefined();
    expect(getItem).not.toHaveBeenCalled();
    expect(setItem).not.toHaveBeenCalled();
    expect(removeItem).not.toHaveBeenCalled();
    expect(key).not.toHaveBeenCalled();
  });

  it.each([
    '{', 'null', '[]', '{}', '{"value":42}', '{"version":1}',
    '{"version":0,"value":42}', '{"version":2,"value":42}', '{"version":"1","value":42}',
  ])('treats malformed or mismatched storage %s as a miss and replaces it on success', async serialized => {
    createReadCache(scope).set('overview', 'superseded');
    localStorage.setItem(storedKey(), serialized);
    const cache = createReadCache(scope);
    expect(cache.get('overview')).toBeUndefined();
    expect(await cache.load('overview', async () => value)).toBe(value);
    expect(createReadCache(scope).get('overview')).toEqual(value);
  });

  it('does not read data stored under an older prefix version', () => {
    createReadCache(scope).set('overview', value);
    const key = storedKey();
    localStorage.setItem(key.replace('msflix:reads:v1:', 'msflix:reads:v0:'), localStorage.getItem(key)!);
    localStorage.removeItem(key);
    expect(createReadCache(scope).get('overview')).toBeUndefined();
  });
});

describe('read-cache invalidation', () => {
  it('purges a prefix from memory and unvisited persistent entries while keeping other scopes and keys', () => {
    const seed = createReadCache(scope);
    seed.set('insights:overview', value);
    seed.set('insights:detail', { rows: [] });
    seed.set('insights-other', 'similar');
    seed.set('graph', 'graph');
    createReadCache(scope + '-other').set('insights:overview', 'other scope');
    localStorage.setItem('unrelated-preference', 'dark');
    const cache = createReadCache(scope);
    expect(cache.get('insights:overview')).toEqual(value);
    cache.invalidate('insights:');
    expect(cache.get('insights:overview')).toBeUndefined();
    expect(cache.get('insights:detail')).toBeUndefined();
    expect(createReadCache(scope).get('insights:overview')).toBeUndefined();
    expect(createReadCache(scope).get('insights:detail')).toBeUndefined();
    expect(cache.get('insights-other')).toBe('similar');
    expect(cache.get('graph')).toBe('graph');
    expect(createReadCache(scope + '-other').get('insights:overview')).toBe('other scope');
    expect(localStorage.getItem('unrelated-preference')).toBe('dark');
    expect(localStorage.length).toBe(4);
  });

  it.each([undefined, ''])('purges the entire namespace with prefix %j, including keys not loaded in memory', prefix => {
    const seed = createReadCache(scope);
    seed.set('overview', value);
    seed.set('graph', 'graph');
    seed.set('health', 'health');
    createReadCache(scope + '-other').set('overview', 'other scope');
    localStorage.setItem('unrelated-preference', 'dark');
    const cache = createReadCache(scope);
    expect(cache.get('overview')).toEqual(value);
    cache.invalidate(prefix);
    for (const key of ['overview', 'graph', 'health']) {
      expect(cache.get(key)).toBeUndefined();
      expect(createReadCache(scope).get(key)).toBeUndefined();
    }
    expect(createReadCache(scope + '-other').get('overview')).toBe('other scope');
    expect(localStorage.getItem('unrelated-preference')).toBe('dark');
    expect(localStorage.length).toBe(2);
  });

  it('increments the revision and notifies only on invalidation, including empty matches', async () => {
    const cache = createReadCache(scope);
    const { subscribe, getVersion } = cache;
    const observed: number[] = [];
    const first = vi.fn(() => { observed.push(getVersion()); });
    const second = vi.fn();
    const unsubscribe = subscribe(first);
    subscribe(second);
    cache.set('overview', value);
    await cache.load('overview', async () => value);
    await cache.load('graph', async () => value);
    cache.get('overview');
    expect(getVersion()).toBe(0);
    expect(first).not.toHaveBeenCalled();
    expect(second).not.toHaveBeenCalled();
    cache.invalidate('missing:');
    expect(observed).toEqual([1]);
    expect(second).toHaveBeenCalledOnce();
    unsubscribe();
    unsubscribe();
    cache.invalidate();
    expect(getVersion()).toBe(2);
    expect(first).toHaveBeenCalledOnce();
    expect(second).toHaveBeenCalledTimes(2);
    expect(cache.subscribe).toBe(subscribe);
    expect(cache.getVersion).toBe(getVersion);
  });

  it('finishes memory and storage invalidation before notifying consumers', () => {
    const cache = createReadCache(scope);
    cache.set('overview', value);
    const listener = vi.fn(() => {
      expect(cache.getVersion()).toBe(1);
      expect(cache.get('overview')).toBeUndefined();
      expect(createReadCache(scope).get('overview')).toBeUndefined();
    });
    cache.subscribe(listener);
    cache.invalidate();
    expect(listener).toHaveBeenCalledOnce();
  });
});

describe('read-cache storage failures', () => {
  it('works in memory when localStorage is missing', async () => {
    vi.stubGlobal('localStorage', undefined);
    const cache = createReadCache(scope);
    expect(await cache.load('overview', async () => value)).toBe(value);
    expect(cache.get('overview')).toBe(value);
    expect(() => cache.invalidate()).not.toThrow();
    expect(cache.get('overview')).toBeUndefined();
  });

  it('works when access to the localStorage property itself is denied', async () => {
    const original = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')!;
    const denied = vi.fn(() => { throw new DOMException('Storage denied', 'SecurityError'); });
    Object.defineProperty(globalThis, 'localStorage', { configurable: true, get: denied });
    try {
      const memory = createReadCache();
      memory.set('overview', value);
      expect(denied).not.toHaveBeenCalled();
      const cache = createReadCache(scope);
      expect(await cache.load('overview', async () => value)).toBe(value);
      expect(cache.get('overview')).toBe(value);
      cache.invalidate();
      expect(cache.get('overview')).toBeUndefined();
      expect(denied).toHaveBeenCalledOnce();
    } finally {
      Object.defineProperty(globalThis, 'localStorage', original);
    }
  });

  it('treats failed storage reads as misses and still caches a successful fetch in memory', async () => {
    const getItem = vi.spyOn(localStorage, 'getItem').mockImplementation(() => {
      throw new DOMException('Storage denied', 'SecurityError');
    });
    const cache = createReadCache(scope);
    expect(cache.get('overview')).toBeUndefined();
    expect(await cache.load('overview', async () => value)).toBe(value);
    expect(cache.get('overview')).toBe(value);
    expect(getItem).toHaveBeenCalledTimes(2);
  });

  it('removes a superseded persisted value when a replacement exceeds storage quota', async () => {
    createReadCache(scope).set('overview', 'superseded');
    const key = storedKey();
    vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
      throw new DOMException('Storage full', 'QuotaExceededError');
    });
    const removeItem = vi.spyOn(localStorage, 'removeItem');
    const cache = createReadCache(scope);
    expect(() => cache.set('overview', value)).not.toThrow();
    expect(cache.get('overview')).toBe(value);
    expect(removeItem).toHaveBeenCalledWith(key);
    expect(localStorage.getItem(key)).toBeNull();
    expect(createReadCache(scope).get('overview')).toBeUndefined();
    expect(await cache.load('graph', async () => value)).toBe(value);
    expect(cache.get('graph')).toBe(value);
  });

  it('keeps replacement data in memory even if both storage write and cleanup fail', () => {
    createReadCache(scope).set('overview', 'superseded');
    const cache = createReadCache(scope);
    const setItem = vi.spyOn(localStorage, 'setItem').mockImplementation(() => { throw new Error('Write denied'); });
    const removeItem = vi.spyOn(localStorage, 'removeItem').mockImplementation(() => { throw new Error('Delete denied'); });
    expect(() => cache.set('overview', value)).not.toThrow();
    expect(cache.get('overview')).toBe(value);
    expect(removeItem).toHaveBeenCalled();
    expect(() => cache.invalidate()).not.toThrow();
    setItem.mockRestore();
    removeItem.mockRestore();
    expect(cache.get('overview')).toBeUndefined();
  });

  it.each(['length', 'key', 'removeItem'] as const)('still invalidates memory and notifies when storage %s throws', method => {
    const cache = createReadCache(scope);
    cache.set('insights:overview', value);
    cache.set('graph', 'unaffected');
    const listener = vi.fn();
    cache.subscribe(listener);
    const fail = () => { throw new DOMException('Storage denied', 'SecurityError'); };
    const failure = method === 'length'
      ? vi.spyOn(localStorage, 'length', 'get').mockImplementation(fail)
      : vi.spyOn(localStorage, method).mockImplementation(fail);
    expect(() => cache.invalidate('insights:')).not.toThrow();
    failure.mockRestore();
    expect(cache.get('insights:overview')).toBeUndefined();
    expect(cache.get('graph')).toBe('unaffected');
    expect(cache.getVersion()).toBe(1);
    expect(listener).toHaveBeenCalledOnce();
  });
});

describe('read-cache request ownership', () => {
  it('starts the fetcher immediately so its completion callback is available before load returns', async () => {
    const cache = createReadCache(scope);
    let complete!: (result: typeof value) => void;
    const fetcher = vi.fn(() => new Promise<typeof value>(resolve => { complete = resolve; }));
    const request = cache.load('overview', fetcher);
    expect(fetcher).toHaveBeenCalledOnce();
    complete(value);
    expect(await request).toBe(value);
    expect(cache.get('overview')).toBe(value);
  });

  it('installs ownership before invocation so a reentrant same-key load shares its promise', async () => {
    const cache = createReadCache(scope);
    const response = deferred<typeof value>();
    const duplicateFetcher = vi.fn(async () => value);
    let reentrant!: Promise<typeof value>;
    const request = cache.load('overview', () => {
      reentrant = cache.load('overview', duplicateFetcher);
      return response.promise;
    });
    expect(reentrant).toBe(request);
    expect(duplicateFetcher).not.toHaveBeenCalled();
    response.resolve(value);
    expect(await request).toBe(value);
    expect(await reentrant).toBe(value);
  });

  it('honors invalidation called synchronously inside the fetcher', async () => {
    const cache = createReadCache(scope);
    const response = deferred<typeof value>();
    const request = cache.load('overview', () => {
      cache.invalidate();
      return response.promise;
    });
    expect(cache.getVersion()).toBe(1);
    response.resolve(value);
    expect(await request).toBe(value);
    expect(cache.get('overview')).toBeUndefined();
    expect(createReadCache(scope).get('overview')).toBeUndefined();
  });

  it.each(['older', 'newer'] as const)('preserves a reentrant replacement when the %s response settles first', async firstToSettle => {
    const cache = createReadCache(scope);
    const old = deferred<typeof value>();
    const fresh = deferred<typeof value>();
    const newer = { rows: [], count: 0 };
    const fetcher = vi.fn(() => fresh.promise);
    let replacement!: Promise<typeof value>;
    const request = cache.load('overview', () => {
      cache.invalidate('overview');
      replacement = cache.load('overview', fetcher);
      return old.promise;
    });
    expect(fetcher).toHaveBeenCalledOnce();
    expect(replacement).not.toBe(request);
    if (firstToSettle === 'older') {
      old.resolve(value);
      expect(await request).toBe(value);
      expect(cache.get('overview')).toBeUndefined();
      expect(cache.load('overview', fetcher)).toBe(replacement);
    }
    fresh.resolve(newer);
    expect(await replacement).toBe(newer);
    if (firstToSettle === 'newer') {
      old.resolve(value);
      expect(await request).toBe(value);
    }
    expect(cache.get('overview')).toBe(newer);
    expect(createReadCache(scope).get('overview')).toEqual(newer);
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it('keeps a reentrant replacement owned when the original fetcher throws synchronously', async () => {
    const cache = createReadCache(scope);
    const fresh = deferred<typeof value>();
    const fetcher = vi.fn(() => fresh.promise);
    let replacement!: Promise<typeof value>;
    const request = cache.load('overview', () => {
      cache.invalidate();
      replacement = cache.load('overview', fetcher);
      throw new Error('Original failure');
    });
    const callsOnReturn = fetcher.mock.calls.length;
    await expect(request).rejects.toThrow('Original failure');
    expect(callsOnReturn).toBe(1);
    expect(cache.load('overview', fetcher)).toBe(replacement);
    fresh.resolve(value);
    expect(await replacement).toBe(value);
    expect(cache.get('overview')).toBe(value);
  });

  it('deduplicates concurrent misses for one key without blocking other keys or cloning results', async () => {
    const cache = createReadCache(scope);
    const response = deferred<typeof value>();
    const fetcher = vi.fn(() => response.promise);
    const first = cache.load('overview', fetcher);
    const duplicate = cache.load('overview', fetcher);
    expect(duplicate).toBe(first);
    expect(await cache.load('graph', async () => 'independent')).toBe('independent');
    expect(fetcher).toHaveBeenCalledOnce();
    response.resolve(value);
    expect(await first).toBe(value);
    expect(await duplicate).toBe(value);
    expect(cache.get('overview')).toBe(value);
    expect(await cache.load('overview', fetcher)).toBe(value);
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it('never caches rejected requests and permits a fresh retry after a shared failure', async () => {
    const cache = createReadCache(scope);
    const failure = new Error('Read failed');
    const fetcher = vi.fn().mockRejectedValueOnce(failure).mockResolvedValueOnce(value);
    const first = cache.load('overview', fetcher);
    const duplicate = cache.load('overview', fetcher);
    expect(duplicate).toBe(first);
    expect(await Promise.allSettled([first, duplicate])).toEqual([
      { status: 'rejected', reason: failure }, { status: 'rejected', reason: failure },
    ]);
    expect(cache.get('overview')).toBeUndefined();
    expect(createReadCache(scope).get('overview')).toBeUndefined();
    expect(localStorage.length).toBe(0);
    expect(await cache.load('overview', fetcher)).toBe(value);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('turns synchronous fetcher throws into rejected promises and allows retrying', async () => {
    const cache = createReadCache(scope);
    const failure = new Error('Client unavailable');
    const fetcher = vi.fn(() => { throw failure; });
    let request!: Promise<unknown>;
    expect(() => { request = cache.load('overview', fetcher); }).not.toThrow();
    const callsOnReturn = fetcher.mock.calls.length;
    await expect(request).rejects.toBe(failure);
    expect(callsOnReturn).toBe(1);
    expect(cache.get('overview')).toBeUndefined();
    expect(await cache.load('overview', async () => value)).toBe(value);
  });

  it('prevents a pending response from repopulating a fully invalidated cache', async () => {
    const cache = createReadCache(scope);
    const overview = deferred<typeof value>();
    const graph = deferred<typeof value>();
    const first = cache.load('overview', () => overview.promise);
    const second = cache.load('graph', () => graph.promise);
    cache.invalidate();
    overview.resolve(value);
    graph.resolve(value);
    expect(await first).toBe(value);
    expect(await second).toBe(value);
    expect(cache.get('overview')).toBeUndefined();
    expect(cache.get('graph')).toBeUndefined();
    expect(createReadCache(scope).get('overview')).toBeUndefined();
    expect(localStorage.length).toBe(0);
  });

  it('invalidates only matching pending requests and still stores an unrelated response', async () => {
    const cache = createReadCache(scope);
    const insight = deferred<typeof value>();
    const graph = deferred<typeof value>();
    const first = cache.load('insights:overview', () => insight.promise);
    const second = cache.load('graph', () => graph.promise);
    cache.invalidate('insights:');
    insight.resolve(value);
    graph.resolve(value);
    await Promise.all([first, second]);
    expect(cache.get('insights:overview')).toBeUndefined();
    expect(cache.get('graph')).toBe(value);
    expect(createReadCache(scope).get('graph')).toEqual(value);
  });

  it('does not let an old completion cache data or release the newer request ownership', async () => {
    const cache = createReadCache(scope);
    const old = deferred<typeof value>();
    const fresh = deferred<typeof value>();
    const first = cache.load('overview', () => old.promise);
    cache.invalidate('overview');
    const fetcher = vi.fn(() => fresh.promise);
    const second = cache.load('overview', fetcher);
    expect(second).not.toBe(first);
    old.resolve(value);
    expect(await first).toBe(value);
    expect(cache.get('overview')).toBeUndefined();
    expect(cache.load('overview', fetcher)).toBe(second);
    expect(fetcher).toHaveBeenCalledOnce();
    const newer = { rows: [], count: 0 };
    fresh.resolve(newer);
    expect(await second).toBe(newer);
    expect(cache.get('overview')).toBe(newer);
    expect(createReadCache(scope).get('overview')).toEqual(newer);
  });

  it('never overwrites a newer cached and persisted result with a late old completion', async () => {
    const cache = createReadCache(scope);
    const old = deferred<typeof value>();
    const first = cache.load('overview', () => old.promise);
    cache.invalidate();
    const newer = { rows: [], count: 0 };
    expect(await cache.load('overview', async () => newer)).toBe(newer);
    old.resolve(value);
    expect(await first).toBe(value);
    expect(cache.get('overview')).toBe(newer);
    expect(createReadCache(scope).get('overview')).toEqual(newer);
  });

  it('does not let a late rejected request clear a newer pending request', async () => {
    const cache = createReadCache(scope);
    const old = deferred<typeof value>();
    const fresh = deferred<typeof value>();
    const first = cache.load('overview', () => old.promise);
    cache.invalidate();
    const second = cache.load('overview', () => fresh.promise);
    old.reject(new Error('Old failure'));
    await expect(first).rejects.toThrow('Old failure');
    expect(cache.load('overview', async () => value)).toBe(second);
    fresh.resolve(value);
    expect(await second).toBe(value);
    expect(cache.get('overview')).toBe(value);
  });

  it('does not let a pending load overwrite an explicit replacement', async () => {
    const cache = createReadCache(scope);
    const old = deferred<typeof value>();
    const first = cache.load('overview', () => old.promise);
    const newer = { rows: [], count: 0 };
    cache.set('overview', newer);
    old.resolve(value);
    expect(await first).toBe(value);
    expect(cache.get('overview')).toBe(newer);
    expect(createReadCache(scope).get('overview')).toEqual(newer);
  });
});

describe('useReadCache', () => {
  it('uses the provided cache and rerenders only when it is invalidated', async () => {
    const cache = createReadCache(scope);
    const rendered = vi.fn();
    const wrapper = ({ children }: PropsWithChildren) => createElement(ReadCacheContext.Provider, { value: cache }, children);
    const { result } = renderHook(() => { rendered(); return useReadCache(); }, { wrapper });
    expect(result.current).toEqual({ cache, revision: 0 });
    const initialRenders = rendered.mock.calls.length;
    await act(async () => {
      cache.set('overview', value);
      await cache.load('graph', async () => value);
    });
    expect(rendered).toHaveBeenCalledTimes(initialRenders);
    act(() => { cache.invalidate(); });
    expect(result.current).toEqual({ cache, revision: 1 });
    expect(rendered).toHaveBeenCalledTimes(initialRenders + 1);
  });

  it('keeps a stable memory-only fallback per hook, not a shared module cache', () => {
    const first = renderHook(() => useReadCache());
    const second = renderHook(() => useReadCache());
    const cache = first.result.current.cache;
    cache.set('overview', value);
    first.rerender();
    expect(first.result.current.cache).toBe(cache);
    expect(second.result.current.cache).not.toBe(cache);
    expect(second.result.current.cache.get('overview')).toBeUndefined();
    expect(localStorage.length).toBe(0);
    act(() => { cache.invalidate(); });
    expect(first.result.current.revision).toBe(1);
    expect(second.result.current.revision).toBe(0);
    first.unmount();
    expect(renderHook(() => useReadCache()).result.current.cache.get('overview')).toBeUndefined();
  });

  it('switches subscriptions when the provided scope changes', () => {
    const first = createReadCache('first');
    const second = createReadCache('second');
    let provided = first;
    const wrapper = ({ children }: PropsWithChildren) => createElement(ReadCacheContext.Provider, { value: provided }, children);
    const { result, rerender } = renderHook(() => useReadCache(), { wrapper });
    act(() => { first.invalidate(); });
    expect(result.current).toEqual({ cache: first, revision: 1 });
    provided = second;
    rerender();
    expect(result.current).toEqual({ cache: second, revision: 0 });
    act(() => { first.invalidate(); });
    expect(result.current).toEqual({ cache: second, revision: 0 });
    act(() => { second.invalidate(); });
    expect(result.current).toEqual({ cache: second, revision: 1 });
  });

  it('keeps one subscription across rerenders and releases it on unmount', () => {
    const cache = createReadCache();
    const stop = vi.fn();
    const original = cache.subscribe;
    const subscribe = vi.spyOn(cache, 'subscribe').mockImplementation(listener => {
      const unsubscribe = original(listener);
      return () => { unsubscribe(); stop(); };
    });
    const wrapper = ({ children }: PropsWithChildren) => createElement(ReadCacheContext.Provider, { value: cache }, children);
    const { rerender, unmount } = renderHook(() => useReadCache(), { wrapper });
    rerender();
    rerender();
    act(() => { cache.invalidate(); });
    expect(subscribe).toHaveBeenCalledOnce();
    expect(stop).not.toHaveBeenCalled();
    unmount();
    expect(stop).toHaveBeenCalledOnce();
  });
});
