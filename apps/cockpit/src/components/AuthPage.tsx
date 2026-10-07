import { useState } from 'react';
import { ArrowRight } from '@phosphor-icons/react';
import { useAuth } from '@/hooks/AuthContext';
import { safeError } from '@/services/business';

export function AuthPage() {
  const { signIn, error: authError } = useAuth();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  return <main className="auth-page"><div className="auth-card">
    <div className="brand">MS<span>FLIX</span><small>BUSINESS CONTROL</small></div>
    <h1>Behind every story,<br />a connected business.</h1>
    <p>Sign in through the MSFlix app in Microsoft Fabric. Your identity determines whether you can view or operate.</p>
    <button className="primary" disabled={loading} onClick={async () => {
      setLoading(true); setError('');
      try { await signIn(); } catch (err) { setError(safeError(err)); } finally { setLoading(false); }
    }}>{loading ? 'Opening Fabric…' : 'Sign in with Microsoft'}<ArrowRight aria-hidden="true" /></button>
    {(error || authError) && <p role="alert" className="notice">{error || authError}</p>}
    <small>No mock authentication or offline-success mode is available.</small>
  </div></main>;
}
