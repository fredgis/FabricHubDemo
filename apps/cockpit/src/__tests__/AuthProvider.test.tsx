import { StrictMode, type ReactNode } from 'react';
import { act, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AuthProvider, useAuth } from '@/hooks/AuthContext';
import { useReadCache } from '@/hooks/ReadCacheContext';
import { createReadCache } from '@/services/readCache';
import type { IAuthService } from '@/services/IAuthService';

const stubAuthService: IAuthService = {
  fabricAuthEnabled: false,
  async signIn() {
    return { id: 'u1', email: 'dev@contoso.com', name: 'dev' };
  },
  async signOut() {},
  async getCurrentUser() {
    return null;
  },
  async initEmbeddedAuth() {
    return null;
  },
};

describe('AuthProvider', () => {
  it('renders children once initial auth check completes', async () => {
    render(
      <AuthProvider authService={stubAuthService}>
        <div data-testid="content">ready</div>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('content')).toHaveTextContent('ready');
    });
  });
});

const viewer = { id: 'u1', email: 'dev@contoso.com', name: 'dev' };
const authenticatedService = (): IAuthService => ({ ...stubAuthService, getCurrentUser: async () => viewer });
function mountIdentity(service = authenticatedService()) {
  return renderHook(() => ({ auth: useAuth(), ...useReadCache() }), {
    wrapper: ({ children }: { children: ReactNode }) => <StrictMode>
      <AuthProvider authService={service}>{children}</AuthProvider>
    </StrictMode>,
  });
}
afterEach(() => { vi.unstubAllEnvs(); });

it('restores only an authenticated identity cache after a full provider remount', async () => {
  const first = mountIdentity();
  await waitFor(() => expect(first.result.current.auth.user?.id).toBe('u1'));
  first.result.current.cache.set('read:fixture', { count: 7 });
  first.unmount();
  const second = mountIdentity();
  expect(second.result.current.auth.loading).toBe(true);
  expect(second.result.current.cache.get('read:fixture')).toBeUndefined();
  await waitFor(() => expect(second.result.current.auth.user?.id).toBe('u1'));
  expect(second.result.current.cache.get('read:fixture')).toEqual({ count: 7 });
});

it.each(['VITE_RAYFIN_API_URL', 'VITE_FABRIC_WORKSPACE_ID', 'VITE_FABRIC_ITEM_ID'])(
  'isolates persisted reads by %s', async environmentKey => {
    vi.stubEnv(environmentKey, 'first-binding');
    const first = mountIdentity();
    await waitFor(() => expect(first.result.current.auth.user?.id).toBe('u1'));
    first.result.current.cache.set('read:fixture', 'first binding');
    first.unmount();
    vi.stubEnv(environmentKey, 'second-binding');
    const second = mountIdentity();
    await waitFor(() => expect(second.result.current.auth.user?.id).toBe('u1'));
    expect(second.result.current.cache.get('read:fixture')).toBeUndefined();
  },
);

it('purges the signed-out identity, including late reads, without clearing other storage', async () => {
  const foreign = createReadCache('another-app');
  foreign.set('read:fixture', 'unrelated');
  localStorage.setItem('unrelated-preference', 'keep');
  const first = mountIdentity();
  await waitFor(() => expect(first.result.current.auth.user?.id).toBe('u1'));
  const oldCache = first.result.current.cache;
  oldCache.set('read:fixture', 'private');
  let finish!: (value: string) => void;
  const pending = oldCache.load('read:pending', () => new Promise<string>(resolve => { finish = resolve; }));
  await act(async () => { await first.result.current.auth.signOut(); });
  expect(first.result.current.auth.isAuthenticated).toBe(false);
  finish('late private result');
  await pending;
  expect(oldCache.get('read:fixture')).toBeUndefined();
  expect(oldCache.get('read:pending')).toBeUndefined();
  expect(foreign.get('read:fixture')).toBe('unrelated');
  expect(localStorage.getItem('unrelated-preference')).toBe('keep');
  first.unmount();
  const second = mountIdentity();
  await waitFor(() => expect(second.result.current.auth.user?.id).toBe('u1'));
  expect(second.result.current.cache.get('read:fixture')).toBeUndefined();
  expect(second.result.current.cache.get('read:pending')).toBeUndefined();
});

it('purges the previous identity when sign-in switches users', async () => {
  const service = authenticatedService();
  service.signIn = vi.fn().mockResolvedValue({ ...viewer, id: 'u2' });
  const hook = mountIdentity(service);
  await waitFor(() => expect(hook.result.current.auth.user?.id).toBe('u1'));
  const firstCache = hook.result.current.cache;
  firstCache.set('read:fixture', 'first user');
  await act(async () => { await hook.result.current.auth.signIn(); });
  expect(hook.result.current.auth.user?.id).toBe('u2');
  expect(hook.result.current.cache.get('read:fixture')).toBeUndefined();
  expect(firstCache.get('read:fixture')).toBeUndefined();
  hook.unmount();
  const again = mountIdentity();
  await waitFor(() => expect(again.result.current.auth.user?.id).toBe('u1'));
  expect(again.result.current.cache.get('read:fixture')).toBeUndefined();
});
