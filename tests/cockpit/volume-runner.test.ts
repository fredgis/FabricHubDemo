import { describe, expect, it } from 'vitest';
import { runChunks } from '../../apps/cockpit/tools/lib/volume-runner.mjs';
describe('bounded volume checkpoint execution', () => {
  it('resumes from committed chunks and starts no new chunk after cancellation', async () => {
    let stopped = false;
    const committed = new Set([0]);
    const observed: number[] = [];
    const result = await runChunks({
      batches: 3, batchSize: 2, totalOrders: 6,
      checkpoint: async () => ({ committed: [...committed] }),
      execute: async index => { observed.push(index); committed.add(index); stopped = true; },
    }, { concurrency: 1, ordersPerSecond: 10, maxSeconds: 30, shouldStop: () => stopped });
    expect(observed).toEqual([1]);
    expect(result).toEqual({ reason: 'cancelled', committed: [0, 1] });
  });
  it('honors its runtime deadline instead of waiting for a later rate slot', async () => {
    let time=0;
    const observed: number[]=[];
    const result=await runChunks({batches:3,batchSize:2,totalOrders:6,
      checkpoint:async()=>({committed:[]}),execute:async index=>{observed.push(index);}},
      {concurrency:1,ordersPerSecond:1,maxSeconds:1,now:()=>time,sleep:async ms=>{time+=ms;}});
    expect(observed).toEqual([0]);
    expect(result).toEqual({reason:'runtime-limit',committed:[0]});
  });
  it('pauses when the authoritative SQL batch rejects publisher backlog', async () => {
    const result=await runChunks({batches:1,batchSize:2,totalOrders:2,
      checkpoint:async()=>({committed:[]}),execute:async()=>{throw Object.assign(new Error('Backlog'),{code:'VOLUME_BACKLOG_LIMIT'});}},
      {concurrency:1,ordersPerSecond:10,maxSeconds:30});
    expect(result).toEqual({reason:'backlog-limit',committed:[]});
  });
});
