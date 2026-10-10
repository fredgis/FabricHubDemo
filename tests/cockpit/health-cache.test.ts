import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Health } from '../../apps/cockpit/rayfin/functions/src/domain';

const invoke = vi.hoisted(() => vi.fn());
vi.mock('../../apps/cockpit/src/services/rayfinClient', () => ({
  getRayfinClient: () => ({ functions: { health: { invoke } } }),
}));
import { createHealthReader } from '../../apps/cockpit/src/services/health';

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
  it('reuses success for 30 seconds from completion without extending freshness on a hit', async () => {
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
    await vi.advanceTimersByTimeAsync(1);
    invoke.mockResolvedValueOnce({ ...health, outbox_pending: 1 });
    expect(await read()).toEqual({ health: { ...health, outbox_pending: 1 }, checkedAt: Date.parse('2026-10-10T12:00:33.850Z') });
    expect(invoke).toHaveBeenCalledTimes(2);
  });

  it('forces a fresh read before expiry and coalesces concurrent automatic and forced checks', async () => {
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

  it.each(['initial', 'forced', 'expired'] as const)('does not cache a failed %s check or fall back to an older success', async kind => {
    const read = createHealthReader();
    if (kind !== 'initial') await read();
    if (kind === 'expired') await vi.advanceTimersByTimeAsync(30_000);
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

  it('never polls or persists health data in browser storage', async () => {
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
});
