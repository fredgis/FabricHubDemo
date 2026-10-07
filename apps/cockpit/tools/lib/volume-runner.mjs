/**
 * Scheduler around the persisted chunk boundary. Database receipts, never a
 * local cursor, are the source of truth after cancellation or a lost response.
 */
export async function runChunks(backend, options) {
  const { concurrency, ordersPerSecond, maxSeconds } = options;
  if (!Number.isInteger(concurrency) || concurrency < 1 || concurrency > 2)
    throw new Error('Concurrency must be 1-2 for the demo F16 budget.');
  if (!Number.isFinite(ordersPerSecond) || ordersPerSecond < 1 || ordersPerSecond > 100)
    throw new Error('Orders per second must be 1-100.');
  if (!Number.isFinite(maxSeconds) || maxSeconds < 1 || maxSeconds > 3600)
    throw new Error('A run segment must be bounded to at most 3600 seconds.');
  const now = options.now ?? (() => performance.now());
  const sleep = options.sleep ?? (ms => new Promise(resolve => setTimeout(resolve, ms)));
  const deadline = now() + maxSeconds * 1000;
  const initial = await backend.checkpoint();
  const committed = new Set(initial.committed);
  const pending = Array.from({ length: backend.batches }, (_, i) => i).filter(i => !committed.has(i));
  let next = 0;
  let nextPermit = now();
  let reason = '';
  let failure;
  async function stopped() {
    if (reason) return true;
    if (await options.shouldStop?.()) { reason = 'cancelled'; return true; }
    if (now() >= deadline) { reason = 'runtime-limit'; return true; }
    return false;
  }
  async function worker() {
    while (!await stopped()) {
      const index = pending[next++];
      if (index === undefined) return;
      const orders = Math.min(backend.batchSize, backend.totalOrders - index * backend.batchSize);
      const permit = Math.max(nextPermit, now());
      nextPermit = permit + orders / ordersPerSecond * 1000;
      if (permit >= deadline) { reason = 'runtime-limit'; return; }
      // Sleep in bounded intervals so cancellation does not wait for a large chunk's rate slot.
      while (now() < permit) {
        await sleep(Math.min(250, permit - now()));
        if (await stopped()) return;
      }
      if (await stopped()) return;
      try {
        await backend.execute(index);
        committed.add(index);
        await options.onCheckpoint?.([...committed].sort((a,b) => a-b));
      } catch (error) {
        if (error?.code === 'VOLUME_BACKLOG_LIMIT') { reason = 'backlog-limit'; return; }
        failure = error; reason = 'failed'; return;
      }
    }
  }
  await Promise.all(Array.from({ length: concurrency }, async()=>{
    try{await worker();}catch(error){failure=error;reason='failed';}
  }));
  if (failure) throw failure;
  return { reason: committed.size === backend.batches ? 'completed' : reason || 'paused',
    committed: [...committed].sort((a,b) => a-b) };
}
