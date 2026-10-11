export interface ReadCache {
  get<T>(key: string): T | undefined;
  set<T>(key: string, value: T): void;
  load<T>(key: string, fetcher: () => Promise<T>): Promise<T>;
  invalidate(prefix?: string): void;
  subscribe(listener: () => void): () => void;
  getVersion(): number;
}

export function createReadCache(namespace?: string): ReadCache {
  const values = new Map<string, unknown>();
  const pending = new Map<string, Promise<unknown>>();
  const listeners = new Set<() => void>();
  const storagePrefix = `msflix:reads:v1:${JSON.stringify(namespace)}:`;
  let version = 0;
  let allowStorageReads = true;
  let storage: Storage | undefined;
  try {
    storage = namespace === undefined ? undefined : globalThis.localStorage;
  } catch {
    storage = undefined;
  }

  const removeStored = (storageKey: string): void => {
    try {
      storage?.removeItem(storageKey);
    } catch {
      allowStorageReads = false;
    }
  };

  const get = <T>(key: string): T | undefined => {
    if (values.has(key)) return values.get(key) as T;
    if (!storage || !allowStorageReads) return undefined;
    const storageKey = storagePrefix + key;
    try {
      const serialized = storage.getItem(storageKey);
      if (serialized === null) return undefined;
      const entry: unknown = JSON.parse(serialized);
      if (typeof entry !== 'object' || entry === null
        || !('version' in entry) || entry.version !== 1 || !('value' in entry)) {
        removeStored(storageKey);
        return undefined;
      }
      values.set(key, entry.value);
      return entry.value as T;
    } catch {
      removeStored(storageKey);
      return undefined;
    }
  };

  const set = <T>(key: string, value: T): void => {
    values.set(key, value);
    pending.delete(key);
    if (!storage) return;
    const storageKey = storagePrefix + key;
    try {
      storage.setItem(storageKey, JSON.stringify({ version: 1, value }));
    } catch {
      removeStored(storageKey);
    }
  };

  const load = <T>(key: string, fetcher: () => Promise<T>): Promise<T> => {
    const cached = get<T>(key);
    if (cached !== undefined) return Promise.resolve(cached);
    const existing = pending.get(key);
    if (existing) return existing as Promise<T>;
    let resolve!: (value: T | PromiseLike<T>) => void;
    let reject!: (error: unknown) => void;
    const result = new Promise<T>((complete, fail) => { resolve = complete; reject = fail; });
    const request = result.then(value => {
      if (pending.get(key) === request) set(key, value);
      return value;
    }).finally(() => {
      if (pending.get(key) === request) pending.delete(key);
    });
    pending.set(key, request);
    try {
      resolve(fetcher());
    } catch (error) {
      reject(error);
    }
    return request;
  };

  const invalidate = (prefix = ''): void => {
    for (const key of values.keys()) {
      if (key.startsWith(prefix)) values.delete(key);
    }
    for (const key of pending.keys()) {
      if (key.startsWith(prefix)) pending.delete(key);
    }
    if (storage) {
      try {
        for (let index = storage.length - 1; index >= 0; index--) {
          const key = storage.key(index);
          if (key?.startsWith(storagePrefix + prefix)) removeStored(key);
        }
      } catch {
        allowStorageReads = false;
      }
    }
    version++;
    for (const listener of [...listeners]) listener();
  };

  const subscribe = (listener: () => void): (() => void) => {
    listeners.add(listener);
    return () => { listeners.delete(listener); };
  };
  const getVersion = (): number => version;

  return { get, set, load, invalidate, subscribe, getVersion };
}
