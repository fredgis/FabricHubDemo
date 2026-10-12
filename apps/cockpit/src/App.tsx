import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';

import { AuthPage } from '@/components/AuthPage';
import { useAuth } from '@/hooks/AuthContext';
import { HomePage } from '@/pages/HomePage';

function AuthGuard({
  children,
  requireAuth,
}: {
  children: React.ReactNode;
  requireAuth: boolean;
}) {
  const { isAuthenticated, loading } = useAuth();

  if (loading) {
    return (
      <div className="auth-page" aria-busy="true">
        <div role="status">Verifying Fabric identity…</div>
      </div>
    );
  }

  if (requireAuth && !isAuthenticated) return <Navigate to="/auth" replace />;
  if (!requireAuth && isAuthenticated) return <Navigate to="/" replace />;

  return <>{children}</>;
}

function CockpitRoute() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const route = pathname === '/campaign-impact' || pathname === '/dataflow' ? pathname : '/';
  return <HomePage route={route} onNavigate={navigate} />;
}

function App() {
  return (
    <BrowserRouter>
      {/* ensure all new routes require auth */}
      <Routes>
        <Route
          path="/auth"
          element={
            <AuthGuard requireAuth={false}>
              <AuthPage />
            </AuthGuard>
          }
        />
        <Route
          path="/"
          element={
            <AuthGuard requireAuth={true}>
              <CockpitRoute />
            </AuthGuard>
          }
        />
        <Route
          path="/campaign-impact"
          element={
            <AuthGuard requireAuth={true}>
              <CockpitRoute />
            </AuthGuard>
          }
        />
        <Route
          path="/dataflow"
          element={
            <AuthGuard requireAuth={true}>
              <CockpitRoute />
            </AuthGuard>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
