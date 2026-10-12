import { useEffect, useState, type SyntheticEvent } from 'react';
import dataFlowDocument from '@/assets/msflix-dataflow-en.html?raw';

export function DataFlowPage({ onRetry }: { onRetry: () => void }) {
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');

  useEffect(() => {
    if (status !== 'loading') return;
    const timer = window.setTimeout(() => setStatus('error'), 15_000);
    return () => window.clearTimeout(timer);
  }, [status]);

  const loaded = (event: SyntheticEvent<HTMLIFrameElement>) => {
    try {
      const ready = event.currentTarget.contentDocument?.documentElement.dataset.explorerReady === 'true';
      setStatus(ready ? 'ready' : 'error');
    } catch {
      setStatus('error');
    }
  };

  return <section className="dataflow-document" aria-label="Data Flow" aria-busy={status === 'loading'}>
    {status === 'loading' && <p className="dataflow-message" role="status">Loading the MSFlix data flow explorer…</p>}
    {status === 'error' ? <div className="dataflow-message notice" role="alert">
      <h1>Data flow could not load</h1>
      <p>The embedded document did not initialize. Retry this view; your other cockpit pages will not be refreshed.</p>
      <button onClick={onRetry}>Retry data flow</button>
    </div> : <iframe
      className="dataflow-frame"
      title="MSFlix data flow explorer"
      srcDoc={dataFlowDocument}
      allow="clipboard-write"
      onLoad={loaded}
      style={{ visibility: status === 'ready' ? 'visible' : 'hidden' }}
    />}
  </section>;
}
