import { useEffect, useRef, useState } from 'react';
import type { AppFunctionsSchema } from '../../rayfin/functions/src/types';
import { dateLabel, safeError, type Snapshot } from '../services/business';
import { getRayfinClient } from '../services/rayfinClient';
import { clearReloadRetry, readSourceReloads, reloadBlocks, reloadSources, restoreReloadRetry,
  retainReloadRetry, selectReloadCommands, type ReloadCommand, type ReloadInput, type ReloadType } from '../services/source-reloads';

type Props = {
  active?: boolean;
  commands: Snapshot['commands'] | undefined;
  capabilities: AppFunctionsSchema['capabilities']['output'];
  busy?: boolean;
};
const pollIntervalMs = 10_000;
const pollBudgetMs = 60 * 60_000;
const statusHelp: Record<string, string> = {
  requested: 'Queued. The worker may first finish its current propagation cycle.',
  running: 'The source worker is running. Completion has not been reported.',
  completed: 'Completed, as reported by the source worker after chain verification.',
  blocked: 'Blocked. An operator must investigate before either source can be reloaded.',
};

export function SourceReloadControls({ active = true, commands, capabilities, busy = false }: Props) {
  const [restored] = useState(() => {
    try { return { input: restoreReloadRetry(), error: '' }; }
    catch (error) { return { input: undefined, error: safeError(error) }; }
  });
  const [retry, setRetry] = useState(restored.input);
  const retryRef = useRef(retry);
  const [observed, setObserved] = useState<{ snapshot: Props['commands']; rows: ReloadCommand[] }>();
  const [submitting, setSubmitting] = useState<ReloadType>();
  const [reading, setReading] = useState(false);
  const [readError, setReadError] = useState('');
  const [commandError, setCommandError] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const [readAt, setReadAt] = useState<Date>();
  const [paused, setPaused] = useState(false);
  const [readRound, setReadRound] = useState(0);
  const invoking = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    if (!active || !commands || submitting) { setReading(false); return; }
    let current = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const deadline = Date.now() + pollBudgetMs;
    setPaused(false);
    const read = async () => {
      if (Date.now() >= deadline) { setPaused(true); return; }
      setReading(true);
      try {
        const pending = retryRef.current;
        const rows = await readSourceReloads(pending?.idempotency_key);
        if (!current) return;
        const persisted = pending && rows.find(row => row.idempotency_key === pending.idempotency_key);
        if (persisted) {
          if (persisted.type !== pending.type) throw new Error('The retry key belongs to a different source. Ask an operator to inspect the request.');
          clearReloadRetry();
          retryRef.current = undefined; setRetry(undefined);
          setCommandError(''); setAcknowledged(false);
        }
        setObserved({ snapshot: commands, rows }); setReadAt(new Date()); setReadError('');
        if (rows.some(row => row.status === 'requested' || row.status === 'running'))
          timer = setTimeout(() => void read(), pollIntervalMs);
      } catch (error) {
        if (current) setReadError(safeError(error));
      } finally {
        if (current) setReading(false);
      }
    };
    void read();
    return () => { current = false; if (timer) clearTimeout(timer); };
  }, [active, commands, submitting, readRound]);

  const ready = !!commands && observed?.snapshot === commands;
  const rows = observed?.rows ?? selectReloadCommands(commands ?? []);
  const latestBySource = reloadSources.map(source => ({ ...source, command: rows.filter(row => row.type === source.type)
    .sort((a, b) => new Date(b.requested_at).getTime() - new Date(a.requested_at).getTime())[0] }));
  const latestIds = new Set(latestBySource.map(source => source.command?.id));
  const blocked = rows.some(reloadBlocks);
  const unknownStatus = rows.some(row => !Object.hasOwn(statusHelp, row.status));
  const unavailable = !active || !capabilities.can_operate || busy || !!submitting || !ready || reading
    || !!readError || !!restored.error || blocked || unknownStatus;
  const submit = async (type: ReloadType) => {
    if (invoking.current || unavailable || (retryRef.current && retryRef.current.type !== type)) return;
    invoking.current = true; setSubmitting(type); setCommandError(''); setAcknowledged(false);
    try {
      const input: ReloadInput = retryRef.current ?? { type, limit: 1, idempotency_key: crypto.randomUUID() };
      retainReloadRetry(input);
      retryRef.current = input; setRetry(input);
      const result = await getRayfinClient().functions.requestControl.invoke({ input });
      if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(result.entity_key) || result.status !== 'requested')
        throw new Error('The queue acknowledgement could not be verified. Keep the same request key for retry.');
      if (mounted.current) setAcknowledged(true);
    } catch (error) {
      if (mounted.current) setCommandError(safeError(error));
    } finally {
      invoking.current = false;
      if (mounted.current) { setSubmitting(undefined); setReadRound(round => round + 1); }
    }
  };

  return <section className="control-panel" aria-labelledby="source-reload-heading">
    <h2 id="source-reload-heading">Reload source chains</h2>
    <p>Queue one Oracle or Salesforce source chain through Raw, Silver, Gold and graph verification.
      Oracle uses the continuous mirror without restarting CDC. Salesforce starts with a native extraction.</p>
    <p id="source-reload-help">Acceptance means queued, not completed. Only one source reload can be requested,
      running or blocked at a time.</p>
    {!capabilities.can_operate && <p className="permission-note" id="source-reload-permission">
      Source reloads are read-only: {capabilities.reason}</p>}
    {busy && <p className="permission-note">Another cockpit command is in progress.</p>}
    <div className="control-buttons">
      {reloadSources.map(source => <button key={source.type} type="button" style={{ minHeight: 44 }}
        disabled={unavailable || !!retry} onClick={() => void submit(source.type)}
        aria-describedby={!capabilities.can_operate ? 'source-reload-permission' : 'source-reload-help source-reload-status'}>
        {submitting === source.type ? `Requesting ${source.name}…` : `Reload ${source.name}`}
      </button>)}
      <button type="button" disabled aria-describedby="source-reload-sap" style={{ minHeight: 44,
        background: '#242529', color: '#aaa', borderColor: '#505158' }}>SAP unavailable</button>
    </div>
    <p id="source-reload-sap" className="permission-note">SAP reload is not connected yet.</p>
    <div id="source-reload-status" role="status" aria-live="polite" aria-atomic="true">
      {reading && <p>Reading persisted reload status…</p>}
      {submitting && <p>Submitting the request. Completion is not yet confirmed.</p>}
      {acknowledged && <p>Request accepted by the queue. Waiting for persisted status; this is not completion.</p>}
      {latestBySource.map(source => {
        const latest = source.command;
        return <div key={source.type} style={{ marginTop: 16 }}>
          <strong>{source.name}: {latest?.status ?? (ready ? 'no persisted reload request' : 'status not read yet')}</strong>
          {latest && <>
            <p>{statusHelp[latest.status] ?? 'Unexpected status. Ask an operator to inspect this request.'}</p>
            <small className="identifier">Request: {latest.id} · Requested: {dateLabel(latest.requested_at)}
              {latest.completed_at && ` · Finished: ${dateLabel(latest.completed_at)}`}</small>
            {latest.error && <p className="notice">{safeError(new Error(latest.error))}</p>}
          </>}
        </div>;
      })}
      {blocked && <p>Both reload buttons remain disabled until no requested, running or blocked source request remains.</p>}
      {rows.filter(row => reloadBlocks(row) && !latestIds.has(row.id))
        .map(row => <p key={row.id}>An older {row.type === 'reload_oracle' ? 'Oracle' : 'Salesforce'} request
          still holds the lock: {row.status} · <code>{row.id}</code>.
          {row.error && ` ${safeError(new Error(row.error))}`}</p>)}
      {readAt && <p className="permission-note">Last reload status read: {dateLabel(readAt)}.</p>}
      {paused && <p>Automatic status checks paused after 60 minutes. Refresh reload status to resume; no new request is sent.</p>}
    </div>
    {(commandError || readError || restored.error) && <p className="notice" role="alert">
      {commandError && `Request result uncertain: ${commandError} `}
      {readError && `Reload status read failed: ${readError} Automatic checks stopped. `}
      {restored.error}
    </p>}
    {retry && <p className="permission-note">An unconfirmed {retry.type === 'reload_oracle' ? 'Oracle' : 'Salesforce'} request
      retains its original retry key in this tab. Read its status or retry that same request; do not create another.</p>}
    <div className="control-buttons">
      <button type="button" style={{ minHeight: 44 }} disabled={!active || !commands || reading || !!submitting}
        onClick={() => setReadRound(round => round + 1)}>Refresh reload status</button>
      {retry && <button type="button" style={{ minHeight: 44 }} disabled={unavailable}
        onClick={() => void submit(retry.type)}>Retry same {retry.type === 'reload_oracle' ? 'Oracle' : 'Salesforce'} request</button>}
    </div>
  </section>;
}
