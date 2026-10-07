import { createRoot } from 'react-dom/client';

import App from '@/App';
import { AuthProvider } from '@/hooks/AuthContext';
import { bootstrapAuth } from '@/services/bootstrap';

import './main.css';

const root = createRoot(document.getElementById('root')!);
try {
  const authService = bootstrapAuth();
  root.render(<AuthProvider authService={authService}><App /></AuthProvider>);
} catch (error) {
  root.render(<main className="auth-page"><section className="auth-card" role="alert">
    <div className="brand">MS<span>FLIX</span></div><h1>Connection not configured</h1>
    <p>{error instanceof Error ? error.message : 'MSFlix could not initialize its connection.'}</p>
    <p>No mock data or successful service state has been substituted.</p>
  </section></main>);
}
