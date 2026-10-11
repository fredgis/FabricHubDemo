import { lazy } from 'react';
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { DeferredPanel } from '../../apps/cockpit/src/components/DeferredPanel';
import { canPrefetch, duringIdle } from '../../apps/cockpit/src/services/deferred';

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });

it('announces a deferred panel until its module finishes loading', async () => {
  let resolve!: (value: { default: () => React.ReactNode }) => void;
  const load = vi.fn(() => new Promise<{ default: () => React.ReactNode }>(accept => { resolve = accept; }));
  const Panel = lazy(load);
  expect(load).not.toHaveBeenCalled();
  render(<DeferredPanel label="Fixture panel"><Panel /></DeferredPanel>);
  expect(screen.getByRole('status')).toHaveTextContent('Loading Fixture panel');
  await act(async () => { resolve({ default: () => <p>Fixture panel ready</p> }); });
  expect(screen.getByText('Fixture panel ready')).toBeInTheDocument();
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  expect(load).toHaveBeenCalledOnce();
});

it('keeps plain answer text and exposes recovery when a deferred module fails', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  const Panel = lazy(() => Promise.reject(new Error('Fixture module unavailable')));
  render(<DeferredPanel label="Flixy formatting" fallback={<p>Fixture answer stays readable</p>}><Panel /></DeferredPanel>);
  expect(await screen.findByRole('alert')).toHaveTextContent('Flixy formatting could not load');
  expect(screen.getByText('Fixture answer stays readable')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Reload cockpit' })).toBeEnabled();
});

it('avoids preloading hidden documents and constrained connections', () => {
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  vi.stubGlobal('navigator', { connection: { effectiveType: '4g' } });
  expect(canPrefetch()).toBe(true);
  for (const connection of [{ saveData: true }, { effectiveType: '2g' }, { effectiveType: 'slow-2g' }]) {
    vi.stubGlobal('navigator', { connection });
    expect(canPrefetch()).toBe(false);
  }
  vi.stubGlobal('navigator', {});
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
  expect(canPrefetch()).toBe(false);
});

it('cancels an idle task before it starts', () => {
  vi.useFakeTimers();
  const work = vi.fn();
  const cancel = duringIdle(work);
  cancel();
  vi.runAllTimers();
  expect(work).not.toHaveBeenCalled();
});
