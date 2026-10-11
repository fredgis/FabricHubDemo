import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { type AuthUser, type IAuthService } from '@/services/IAuthService';
import { createReadCache } from '@/services/readCache';
import { ReadCacheContext } from '@/hooks/ReadCacheContext';

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  error: string | null;
  signIn: () => Promise<AuthUser>;
  signOut: () => Promise<void>;
  isAuthenticated: boolean;
  fabricAuthEnabled: boolean;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

interface AuthProviderProps {
  children: ReactNode;
  authService: IAuthService;
}

export function AuthProvider({ children, authService }: AuthProviderProps) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const namespace = user ? JSON.stringify([
    import.meta.env.VITE_RAYFIN_API_URL, import.meta.env.VITE_FABRIC_WORKSPACE_ID,
    import.meta.env.VITE_FABRIC_ITEM_ID, user.id,
  ]) : undefined;
  const readCache = useMemo(() => createReadCache(namespace), [namespace]);
  const previousCache = useRef(readCache);
  useEffect(() => {
    if (previousCache.current !== readCache) previousCache.current.invalidate();
    previousCache.current = readCache;
  }, [readCache]);

  useEffect(() => {
    let cancelled = false;
    authService
      .initEmbeddedAuth()
      .then((embedded) => embedded ?? authService.getCurrentUser())
      .then((current) => {
        if (!cancelled && current) setUser(current);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setUser(null);
          setError(err instanceof Error ? err.message : 'Fabric authentication failed.');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [authService]);

  const signIn = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const loggedInUser = await authService.signIn();
      setUser(loggedInUser);
      return loggedInUser;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Login failed';
      setError(message);
      throw err;
    } finally {
      setLoading(false);
    }
  }, [authService]);

  const signOut = useCallback(async () => {
    try {
      await authService.signOut();
      readCache.invalidate();
      setUser(null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-out failed.');
    }
  }, [authService, readCache]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      error,
      signIn,
      signOut,
      isAuthenticated: !!user,
      fabricAuthEnabled: authService.fabricAuthEnabled,
    }),
    [user, loading, error, signIn, signOut, authService]
  );

  return <AuthContext.Provider value={value}>
    <ReadCacheContext.Provider value={readCache}>{children}</ReadCacheContext.Provider>
  </AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
