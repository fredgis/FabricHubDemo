import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Health } from '../../apps/cockpit/rayfin/functions/src/domain';

const invoke = vi.hoisted(() => vi.fn());
vi.mock('../../apps/cockpit/src/services/rayfinClient', () => ({
  getRayfinClient: () => ({ functions: { health: { invoke } } }),
}));
import { createHealthReader } from '../../apps/cockpit/src/services/health';
import { createReadCache } from '../../apps/cockpit/src/services/readCache';

const health: Health = { database: 'Test database', functions: 'Native function', outbox_pending: 3, broker: 'Test delivery status' };

function deferred() {
  let resolve!: (value: Health) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<Health>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-10T12:00:00Z'));
  invoke.mockReset();
  invoke.mockResolvedValue(health);
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe('Operations health cache', () => {
  it('reuses success and its original timestamp until an explicit recheck', async () => {
    const response = deferred();
    invoke.mockReturnValueOnce(response.promise);
    const read = createHealthReader();
    const first = read();
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(3_850);
    response.resolve(health);
    const completed = await first;
    expect(completed).toEqual({ health, checkedAt: Date.parse('2026-10-10T12:00:03.850Z') });
    await vi.advanceTimersByTimeAsync(29_999);
    expect(await read()).toBe(completed);
    expect(invoke).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(24 * 60 * 60_000);
    expect(await read()).toBe(completed);
    expect(invoke).toHaveBeenCalledOnce();
    invoke.mockResolvedValueOnce({ ...health, outbox_pending: 1 });
    expect(await read(true)).toEqual({ health: { ...health, outbox_pending: 1 }, checkedAt: Date.now() });
    expect(invoke).toHaveBeenCalledTimes(2);
  });

  it('forces a fresh read and coalesces concurrent automatic and forced checks', async () => {
    const read = createHealthReader();
    await read();
    const response = deferred();
    invoke.mockReturnValueOnce(response.promise);
    const forced = read(true);
    const automatic = read();
    const duplicate = read(true);
    await Promise.resolve();
    expect(invoke).toHaveBeenCalledTimes(2);
    expect(automatic).toBe(forced);
    expect(duplicate).toBe(forced);
    response.resolve({ ...health, outbox_pending: 0 });
    const results = await Promise.all([forced, automatic, duplicate]);
    expect(results.every(result => result.health.outbox_pending === 0)).toBe(true);
  });

  it('coalesces initial checks while the native read is pending', async () => {
    const response = deferred();
    invoke.mockReturnValueOnce(response.promise);
    const read = createHealthReader();
    const first = read();
    const second = read();
    await Promise.resolve();
    expect(invoke).toHaveBeenCalledOnce();
    response.resolve(health);
    expect(await first).toEqual(await second);
  });

  it.each(['initial', 'forced'] as const)('does not cache a failed %s check or fall back to an older success', async kind => {
    const read = createHealthReader();
    if (kind !== 'initial') await read();
    const failure = new Error('Health access denied');
    invoke.mockRejectedValueOnce(failure);
    await expect(read(kind === 'forced')).rejects.toBe(failure);
    invoke.mockRejectedValueOnce(new Error('Health still unavailable'));
    await expect(read()).rejects.toThrow('Health still unavailable');
    expect((await read()).health).toEqual(health);
    expect(invoke).toHaveBeenCalledTimes(kind === 'initial' ? 3 : 4);
  });

  it('retries after a synchronous SDK failure', async () => {
    const read = createHealthReader();
    invoke.mockImplementationOnce(() => { throw new Error('Client unavailable'); });
    await expect(read()).rejects.toThrow('Client unavailable');
    expect((await read()).health).toEqual(health);
    expect(invoke).toHaveBeenCalledTimes(2);
  });

  it('does not share cached or late results between authenticated cockpit instances', async () => {
    const oldResponse = deferred();
    invoke.mockReturnValueOnce(oldResponse.promise).mockResolvedValueOnce({ ...health, outbox_pending: 0 });
    const oldRead = createHealthReader();
    const oldRequest = oldRead();
    const newRead = createHealthReader();
    expect((await newRead()).health.outbox_pending).toBe(0);
    oldResponse.resolve(health);
    await oldRequest;
    expect((await newRead()).health.outbox_pending).toBe(0);
    expect(invoke).toHaveBeenCalledTimes(2);
  });

  it('never polls and only persists when an authenticated cache is supplied', async () => {
    const localWrite = vi.spyOn(localStorage, 'setItem');
    const sessionWrite = vi.spyOn(Storage.prototype, 'setItem');
    const read = createHealthReader();
    await read();
    await vi.advanceTimersByTimeAsync(120_000);
    expect(invoke).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
    expect(localWrite).not.toHaveBeenCalled();
    expect(sessionWrite).not.toHaveBeenCalled();
  });

  it('persists an authenticated check until explicit recheck or business invalidation', async () => {
    const first = createHealthReader(createReadCache('health-user'));
    const completed = await first();
    await vi.advanceTimersByTimeAsync(6 * 60_000);
    const cache = createReadCache('health-user');
    const restored = createHealthReader(cache);
    expect(await restored()).toEqual(completed);
    expect(invoke).toHaveBeenCalledOnce();
    await restored(true);
    expect(invoke).toHaveBeenCalledTimes(2);
    cache.invalidate('read:');
    await restored();
    expect(invoke).toHaveBeenCalledTimes(3);
    expect((await createHealthReader(createReadCache('another-user'))()).health).toEqual(health);
    expect(invoke).toHaveBeenCalledTimes(4);
  });
});
