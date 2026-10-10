import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReloadCommand, ReloadInput, ReloadType } from '../../apps/cockpit/src/services/source-reloads';

const native = vi.hoisted(() => ({ invoke: vi.fn(), read: vi.fn() }));
vi.mock('../../apps/cockpit/src/services/rayfinClient', () => ({
  getRayfinClient: () => ({ functions: { requestControl: { invoke: native.invoke } } }),
}));
vi.mock('../../apps/cockpit/src/services/source-reloads', async importOriginal => ({
  ...await importOriginal<typeof import('../../apps/cockpit/src/services/source-reloads')>(),
  readSourceReloads: native.read,
}));
import { SourceReloadControls } from '../../apps/cockpit/src/pages/SourceReloadControls';

const commands: [] = [];
const capabilities = { can_operate: true, reason: 'Time-bounded operator grant' };
const id = '11111111-2222-4333-8444-555555555555';
const row = (type: ReloadType, status: string, key = 'persisted-key'): ReloadCommand => ({
  id, idempotency_key: key, type, status, requested_at: new Date('2026-10-07T20:00:00Z'),
});
const renderControls = () => render(<SourceReloadControls commands={commands} capabilities={capabilities} />);
const flush = () => act(async () => {});
beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear();
  native.read.mockResolvedValue([]);
});
afterEach(() => { cleanup(); vi.useRealTimers(); sessionStorage.clear(); });

describe('source reload controls', () => {
  it.each([['reload_oracle', 'Oracle'], ['reload_salesforce', 'Salesforce']] as const)(
    'enqueues %s once and shows requested rather than completed', async (type, name) => {
      let accept!: (value: { entity_key: string; status: string; event_ids: string[] }) => void;
      native.invoke.mockImplementation(({ input }: { input: ReloadInput }) => {
        native.read.mockResolvedValue([row(type, 'requested', input.idempotency_key)]);
        return new Promise(resolve => { accept = resolve; });
      });
      renderControls();
      const button = screen.getByRole('button', { name: `Reload ${name}` });
      await waitFor(() => expect(button).toBeEnabled());
      fireEvent.click(button); fireEvent.click(button);
      expect(native.invoke).toHaveBeenCalledOnce();
      expect(native.invoke).toHaveBeenCalledWith({ input: { type, limit: 1, idempotency_key: expect.any(String) } });
      expect(screen.getByRole('button', { name: `Reload ${name === 'Oracle' ? 'Salesforce' : 'Oracle'}` })).toBeDisabled();
      expect(screen.queryByText(`${name}: completed`)).not.toBeInTheDocument();
      await act(async () => accept({ entity_key: id, status: 'requested', event_ids: [] }));
      expect(await screen.findByText(`${name}: requested`)).toBeInTheDocument();
      expect(screen.getByText(/Queued\. The worker may first finish/)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: `Reload ${name}` })).toBeDisabled();
      expect(native.read).toHaveBeenLastCalledWith(native.invoke.mock.calls[0][0].input.idempotency_key);
    });

  it('keeps SAP genuinely disabled with a reason and does not grant viewer permissions', async () => {
    render(<SourceReloadControls commands={commands} capabilities={{ can_operate: false, reason: 'Viewer' }} />);
    await screen.findByText('Oracle: no persisted reload request');
    expect(screen.getByRole('button', { name: 'Reload Oracle' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Reload Salesforce' })).toBeDisabled();
    const sap = screen.getByRole('button', { name: 'SAP unavailable' });
    expect(sap).toBeDisabled();
    expect(sap).toHaveAccessibleDescription('SAP reload is not connected yet.');
    fireEvent.click(sap);
    expect(native.invoke).not.toHaveBeenCalled();
  });

  it('restores persisted pending status and stops lightweight polling after completion', async () => {
    vi.useFakeTimers();
    native.read.mockResolvedValueOnce([row('reload_oracle', 'requested')])
      .mockResolvedValueOnce([row('reload_oracle', 'running')])
      .mockResolvedValue([row('reload_oracle', 'completed')]);
    renderControls(); await flush();
    expect(screen.getByText('Oracle: requested')).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(10_000));
    expect(screen.getByText('Oracle: running')).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(10_000));
    expect(screen.getByText('Oracle: completed')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reload Salesforce' })).toBeEnabled();
    await act(() => vi.advanceTimersByTimeAsync(30_000));
    expect(native.read).toHaveBeenCalledTimes(3);
    expect(native.invoke).not.toHaveBeenCalled();
  });

  it('retains an older blocked request and redacts its persisted error', async () => {
    native.read.mockResolvedValue([
      { ...row('reload_oracle', 'completed'), id: 'latest', requested_at: new Date('2026-10-08T20:00:00Z') },
      { ...row('reload_oracle', 'blocked'), error: 'Native failure token=hidden-secret' },
    ]);
    renderControls();
    await screen.findByText(/An older Oracle request still holds the lock/);
    expect(screen.getByRole('button', { name: 'Reload Oracle' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Reload Salesforce' })).toBeDisabled();
    expect(document.body).not.toHaveTextContent('hidden-secret');
    expect(native.invoke).not.toHaveBeenCalled();
  });

  it('retains an uncertain invocation key across remount and retries the exact same request', async () => {
    native.invoke.mockRejectedValueOnce(new Error('Response lost token=hidden-secret'));
    const firstView = renderControls();
    const button = screen.getByRole('button', { name: 'Reload Oracle' });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await screen.findByRole('alert');
    expect(document.body).not.toHaveTextContent('hidden-secret');
    const firstInput = native.invoke.mock.calls[0][0].input as ReloadInput;
    firstView.unmount();
    renderControls();
    const retry = await screen.findByRole('button', { name: 'Retry same Oracle request' });
    await waitFor(() => expect(retry).toBeEnabled());
    expect(screen.getByRole('button', { name: 'Reload Salesforce' })).toBeDisabled();
    native.invoke.mockImplementation(async ({ input }: { input: ReloadInput }) => {
      native.read.mockResolvedValue([row(input.type, 'requested', input.idempotency_key)]);
      return { entity_key: id, status: 'requested', event_ids: [] };
    });
    fireEvent.click(retry);
    await screen.findByText('Oracle: requested');
    expect(native.invoke.mock.calls[1][0]).toEqual({ input: firstInput });
    expect(screen.queryByRole('button', { name: 'Retry same Oracle request' })).not.toBeInTheDocument();
  });

  it('stops automatic checks on a read failure and resumes only on explicit refresh', async () => {
    vi.useFakeTimers();
    native.read.mockResolvedValueOnce([row('reload_salesforce', 'running')])
      .mockRejectedValue(new Error('Status unavailable token=hidden-secret'));
    renderControls(); await flush();
    await act(() => vi.advanceTimersByTimeAsync(10_000));
    expect(screen.getByRole('alert')).toHaveTextContent('Automatic checks stopped.');
    expect(document.body).not.toHaveTextContent('hidden-secret');
    await act(() => vi.advanceTimersByTimeAsync(30_000));
    expect(native.read).toHaveBeenCalledTimes(2);
    native.read.mockResolvedValue([row('reload_salesforce', 'completed')]);
    fireEvent.click(screen.getByRole('button', { name: 'Refresh reload status' })); await flush();
    expect(screen.getByText('Salesforce: completed')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(native.invoke).not.toHaveBeenCalled();
  });

  it('bounds polling to one hour and cleans up its timer on unmount', async () => {
    vi.useFakeTimers();
    native.read.mockResolvedValue([row('reload_oracle', 'running')]);
    const view = renderControls(); await flush();
    vi.setSystemTime(Date.now() + 60 * 60_000);
    await act(() => vi.advanceTimersByTimeAsync(10_000));
    expect(screen.getByText(/Automatic status checks paused after 60 minutes/)).toBeInTheDocument();
    expect(native.read).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('button', { name: 'Refresh reload status' })); await flush();
    expect(native.read).toHaveBeenCalledTimes(2);
    view.unmount();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(native.read).toHaveBeenCalledTimes(2);
  });
});
