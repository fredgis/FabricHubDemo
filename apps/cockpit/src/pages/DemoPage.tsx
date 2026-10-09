import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowsClockwise, Play, Stop } from '@phosphor-icons/react';
import type { AppFunctionsSchema } from '../../rayfin/functions/src/types';
import { createDemoPlan, DemoScenario, validateDemoConfig, type DemoConfig, type DemoRunState,
  type DemoScenarioType } from '../domain/demo-scenario';
import { dateLabel, safeError, type Snapshot } from '../services/business';
import { getRayfinClient } from '../services/rayfinClient';

type Capabilities = AppFunctionsSchema['capabilities']['output'];
type Health = AppFunctionsSchema['health']['output'];
type Gold = AppFunctionsSchema['businessViews']['output'];
export type DemoPageProps = {
  snapshot: Snapshot | null;
  capabilities: Capabilities;
  loading?: boolean;
  readError?: string;
  busy?: boolean;
  snapshotUpdatedAt?: Date;
  gold?: Gold;
  goldLoading?: boolean;
  goldError?: string;
  onRefresh: () => Promise<void> | void;
};

/** Explicitly initiated, real command journeys; delivery and publication are read-only evidence. */
export function DemoPage({
  snapshot, capabilities, loading = false, readError = '', busy = false, snapshotUpdatedAt,
  gold, goldLoading = false, goldError = '', onRefresh,
}: DemoPageProps) {
  const [scenario, setScenario] = useState<DemoScenarioType>('rental');
  const [count, setCount] = useState('10');
  const [paceMs, setPaceMs] = useState(1000);
  const [customerMode, setCustomerMode] = useState<'fixed' | 'random'>('fixed');
  const [customerCount, setCustomerCount] = useState('1');
  const [customerKey, setCustomerKey] = useState('');
  const [runState, setRunState] = useState<DemoRunState>();
  const [commandError, setCommandError] = useState('');
  const [health, setHealth] = useState<Health>();
  const [healthReadAt, setHealthReadAt] = useState<Date>();
  const [healthError, setHealthError] = useState('');
  const [refreshError, setRefreshError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const runner = useRef<DemoScenario | undefined>(undefined);
  const refreshInFlight = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; runner.current?.cancel(); };
  }, []);

  const selectedCustomer = customerKey || snapshot?.customers[0]?.customer_key || '';
  const config: DemoConfig = customerMode === 'random'
    ? { scenario, count: Number(count), paceMs, customerMode, customerCount: Number(customerCount) }
    : { scenario, count: Number(count), paceMs, customerKey: selectedCustomer };
  const invalidCount = !Number.isInteger(config.count) || config.count < 1 || config.count > 100;
  let configurationError = '';
  if (snapshot) {
    try { validateDemoConfig(config, snapshot); }
    catch (error) { configurationError = safeError(error); }
  }
  const invalidCustomerCount = config.customerMode === 'random' && (!Number.isInteger(config.customerCount)
    || config.customerCount < 1 || config.customerCount > config.count || (!invalidCount && !!configurationError));
  const running = runState?.status === 'running';
  const failed = runState?.status === 'failed';
  const canOperate = capabilities.can_operate && !loading && !readError && !busy && !!snapshot;
  const blockedReason = !capabilities.can_operate ? `Demo is read-only: ${capabilities.reason}`
    : busy ? 'Another cockpit command is in progress.'
      : loading ? 'Waiting for the existing customer, offer, and catalog read.'
        : readError ? `Operational read failed: ${readError}`
          : !snapshot ? 'Existing customer, offer, and catalog data must be loaded first.'
            : failed ? 'Retry the paused run with its original keys before starting a new demo.'
              : configurationError;

  const execute = async (current: DemoScenario) => {
    setCommandError('');
    try {
      await current.execute(state => { if (mounted.current) setRunState(state); });
    } catch (error) {
      if (mounted.current) setCommandError(safeError(error));
    }
  };
  const start = (event: FormEvent) => {
    event.preventDefault();
    if (!canOperate || configurationError || runner.current?.state.status === 'running'
      || runner.current?.state.status === 'failed' || !snapshot) return;
    try {
      const current = new DemoScenario(createDemoPlan(config, snapshot), getRayfinClient().functions);
      runner.current = current;
      setRunState(current.state);
      void execute(current);
    } catch (error) { setCommandError(safeError(error)); }
  };
  const resume = () => {
    const current = runner.current;
    if (canOperate && current && ['failed', 'cancelled'].includes(current.state.status)) void execute(current);
  };
  const refreshEvidence = async () => {
    if (refreshInFlight.current) return;
    refreshInFlight.current = true;
    setRefreshing(true); setHealthError(''); setRefreshError(''); setHealth(undefined);
    try {
      await Promise.all([
        Promise.resolve().then(onRefresh).catch(error => {
          if (mounted.current) setRefreshError(safeError(error));
        }),
        Promise.resolve().then(() => getRayfinClient().functions.health.invoke()).then(value => {
          if (!Number.isSafeInteger(value.outbox_pending) || value.outbox_pending < 0)
            throw new Error('Native health returned an invalid outbox pending count.');
          if (mounted.current) { setHealth(value); setHealthReadAt(new Date()); }
        }).catch(error => { if (mounted.current) setHealthError(safeError(error)); }),
      ]);
    } finally {
      refreshInFlight.current = false;
      if (mounted.current) setRefreshing(false);
    }
  };

  const receipts = runState?.receipts ?? [];
  const runCustomerCount = new Set(runner.current?.plan.transactions.map(row => row.customerKey)).size;
  const eventIds = [...new Set(receipts.flatMap(row => row.result.event_ids))];
  const outbox = new Map(snapshot?.outbox.map(row => [row.event_id, row]) ?? []);
  const acknowledged = eventIds.filter(id => outbox.get(id)?.published_at).length;
  const observedPending = eventIds.filter(id => outbox.has(id) && !outbox.get(id)?.published_at).length;
  const unobserved = eventIds.filter(id => !outbox.has(id)).length;
  const orderIds = [...new Set(receipts.filter(row => row.command === 'placeOrder').map(row => row.result.entity_key))];
  const sessionIds = [...new Set(receipts.filter(row => row.command === 'startPlayback').map(row => row.result.entity_key))];
  const goldOrders = gold ? orderIds.filter(id => gold.orders.some(row => row.order_id === id)).length : undefined;
  const goldSessions = gold ? sessionIds.filter(id => gold.sessions.some(row => row.session_id === id)).length : undefined;
  const publication = gold?.dashboard.freshness.published_at;

  return <>
    <section className="control-panel" aria-labelledby="demo-launch-heading">
      <h2 id="demo-launch-heading">Launch a bounded demo</h2>
      <p>Persist actual fictional-customer rentals or purchases, start playback, and record progress.
        The server derives prices and viewing rights. No bank charge, invoice, or fabricated event counter.</p>
      <form onSubmit={start} aria-describedby="demo-launch-help">
        <fieldset disabled={running || busy} style={{ border: 0, padding: 0, margin: 0, minWidth: 0,
          display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(180px, 100%), 1fr))', gap: 20 }}>
          <legend className="sr-only">Demo scenario settings</legend>
          <label htmlFor="demo-scenario">Scenario
            <select id="demo-scenario" value={scenario} onChange={event => setScenario(event.target.value as DemoScenarioType)}>
              <option value="rental">Rental & playback</option>
              <option value="purchase">Purchase & playback</option>
              <option value="mixed">Alternating rentals & purchases</option>
            </select>
          </label>
          <label htmlFor="demo-customer-mode">Customer selection
            <select id="demo-customer-mode" value={customerMode}
              onChange={event => setCustomerMode(event.target.value as 'fixed' | 'random')}>
              <option value="fixed">Fixed customer</option>
              <option value="random">Random Customer</option>
            </select>
          </label>
          {customerMode === 'random' ? <div>
            <label htmlFor="demo-customer-count">Random customer count
              <input id="demo-customer-count" type="number" min={1} max={invalidCount ? 100 : config.count}
                step={1} required value={customerCount} aria-invalid={invalidCustomerCount || undefined}
                aria-describedby="demo-customer-count-help" onChange={event => setCustomerCount(event.target.value)} />
            </label>
            <small id="demo-customer-count-help" aria-live="polite">{invalidCustomerCount
              ? configurationError || 'Random customer count must be a whole number from 1 to the journey count.'
              : 'At least one journey per customer. The journey count is the total, not per customer.'}</small>
          </div> : <label htmlFor="demo-customer">Existing customer
            <select id="demo-customer" value={selectedCustomer} onChange={event => setCustomerKey(event.target.value)}>
              {!snapshot?.customers.length && <option value="">No customers loaded</option>}
              {snapshot?.customers.map(customer => <option key={customer.customer_key} value={customer.customer_key}>
                {customer.name} · {customer.territory} · {customer.customer_key}
              </option>)}
            </select>
          </label>}
          <div>
            <label htmlFor="demo-count">Journey count
              <input id="demo-count" type="number" min={1} max={100} step={1} required value={count}
                aria-invalid={invalidCount || undefined} aria-describedby="demo-count-help"
                onChange={event => setCount(event.target.value)} />
            </label>
            <small id="demo-count-help">{invalidCount ? 'Journey count must be a whole number from 1 to 100.'
              : '1–100 journeys. Three real commands per journey.'}</small>
          </div>
          <label htmlFor="demo-pace">Pace between commands
            <select id="demo-pace" value={paceMs} onChange={event => setPaceMs(Number(event.target.value))}>
              <option value={0}>No added delay</option>
              <option value={250}>250 milliseconds</option>
              <option value={1000}>1 second</option>
              <option value={2000}>2 seconds</option>
            </select>
          </label>
        </fieldset>
        <p id="demo-launch-help" style={{ marginTop: 20 }}>
          One order, one playback start, and one position update per journey. Only existing territorial offers
          are used. {customerMode === 'random' && 'Random Customer selects customers and catalogue films once per run. '}
          Commands run sequentially; retries keep the original parameters and idempotency keys.
        </p>
        {blockedReason && <p className="permission-note" id="demo-blocked">{blockedReason}</p>}
        <div className="control-buttons">
          <button className="primary" type="submit" disabled={!canOperate || !!configurationError || running || failed}
            aria-describedby={blockedReason ? 'demo-blocked' : 'demo-launch-help'}>
            <Play aria-hidden="true" /> Start demo
          </button>
          <button type="button" disabled={!running || runState?.cancelRequested}
            onClick={() => runner.current?.cancel()}>
            <Stop aria-hidden="true" />{runState?.cancelRequested && running ? 'Stopping after current command…' : 'Cancel demo'}
          </button>
          {runState && ['failed', 'cancelled'].includes(runState.status) && <button type="button"
            disabled={!canOperate} onClick={resume}>
            <Play aria-hidden="true" />{failed ? 'Retry same run' : 'Resume same run'}
          </button>}
        </div>
      </form>
      {loading && !snapshot && <p role="status">Loading existing customers, offers, and catalog…</p>}
      {readError && <p className="notice" role="alert">Demo is disabled while the operational read is failing: {readError}</p>}
      {(commandError || runState?.error) && <p className="notice" role="alert" style={{ marginTop: 20 }}>
        {commandError || runState?.error} No subsequent command was issued. Retry the same run to reuse its keys.
      </p>}
      {runState && <div className="receipt" role="status" aria-live="polite" style={{ marginTop: 20, marginBottom: 0 }}>
        <strong>{runState.status === 'completed' ? `All ${runner.current?.plan.transactions.length} journeys completed.`
          : runState.status === 'cancelled' ? 'Demo cancelled at a command boundary.'
            : runState.status === 'failed' ? 'Demo paused on a command failure.'
              : runState.cancelRequested ? 'Stopping after the in-flight command returns.' : 'Demo commands are running.'}</strong>
        <span>{runState.completedTransactions} completed journeys · {receipts.length} confirmed command receipts</span>
        <span>{runCustomerCount} distinct {runCustomerCount === 1 ? 'customer' : 'customers'} in this run.</span>
        <span>Run ID: <code>{runState.runId}</code></span>
        <small>Cancel stops unsent commands; it does not roll back persisted orders or abort a native invocation.
          Switching tabs keeps this run and its retry keys. Signing out stops the next command.</small>
      </div>}
    </section>

    <section aria-labelledby="demo-propagation-heading">
      <div className="page-heading">
        <div><h2 id="demo-propagation-heading">Generation is not delivery</h2>
          <p>Command persistence, Kafka acknowledgements, and Gold publication are separate evidence.</p></div>
        <button type="button" onClick={() => void refreshEvidence()} disabled={refreshing || loading}>
          <ArrowsClockwise aria-hidden="true" />{refreshing ? 'Reading evidence…' : 'Refresh receipts & publication'}
        </button>
      </div>
      {(healthError || refreshError) && <p className="notice" role="alert">
        {healthError && `Health read failed: ${healthError} `}{refreshError && `Data refresh failed: ${refreshError}`}
      </p>}
      <div className="playback-grid">
        <article className="playback-card"><h3>Generated</h3>
          <strong className="segment-number">{eventIds.length}</strong>
          <p>Distinct event IDs returned by confirmed command receipts.</p>
          <small>This is persisted generation, not a Kafka delivery counter.</small>
        </article>
        <article className="playback-card"><h3>Kafka ACK</h3>
          <strong className="segment-number">{acknowledged} of {eventIds.length}</strong>
          <p>{observedPending} observed pending · {unobserved} not observed in the current outbox read.</p>
          <p><strong>Outbox pending:</strong> {health ? health.outbox_pending : 'Not read yet'}</p>
          <small>ACK evidence is the outbox published_at marker, written by the external publisher after broker acknowledgement.
            Missing rows are unknown, not delivery failures. The existing outbox read is limited to its latest window.</small>
          <small style={{ display: 'block', marginTop: 8 }}>Outbox read: {snapshotUpdatedAt ? dateLabel(snapshotUpdatedAt) : 'No timestamp supplied'}.
            {healthReadAt && ` Total pending last read: ${dateLabel(healthReadAt)}.`}</small>
          {health && <small style={{ display: 'block', marginTop: 8 }}>{health.broker}</small>}
        </article>
        <article className="playback-card"><h3>Gold published</h3>
          <strong className="segment-number">{goldLoading ? 'Reading…' : goldError ? 'Read failed'
            : publication ? 'Published' : gold ? 'Unpublished' : 'Not read yet'}</strong>
          {goldError ? <p role="alert">{goldError}</p>
            : <p>Last Gold publication: {publication ? dateLabel(publication) : 'No publication timestamp observed'}.</p>}
          {gold && !goldLoading && <p>{goldOrders} of {orderIds.length} run orders and {goldSessions} of {sessionIds.length} run sessions
            observed in the current Gold window.</p>}
          <small>Event-level publication is not verified for this run. A publication timestamp alone does not prove every event arrived
            or that the newest progress is materialized.</small>
        </article>
      </div>
      <p className="permission-note" style={{ marginTop: 18 }}>Refresh reads status only. It does not start a publisher,
        refresh a pipeline, or publish Gold. Automatic end-to-end propagation is not claimed by this tab.</p>
    </section>

    <section className="playback-section" aria-labelledby="demo-receipts-heading">
      <h2 id="demo-receipts-heading">Actual command receipts</h2>
      {!receipts.length ? <p className="muted">No Demo commands have returned receipts yet. Nothing runs until an authorized operator selects Start demo.</p>
        : <div className="table-scroll"><table>
          <caption className="sr-only">Confirmed Demo commands with server-returned entity and event IDs</caption>
          <thead><tr><th scope="col">Journey / command</th><th scope="col">Order / playback ID</th>
            <th scope="col">Event IDs</th><th scope="col">Receipt / retry key</th></tr></thead>
          <tbody>{receipts.map(receipt => <tr key={receipt.idempotencyKey}>
            <td><strong>{receipt.transactionIndex + 1} · {receipt.command}</strong>
              <small className="identifier">Customer: {runner.current?.plan.transactions[receipt.transactionIndex].customerKey}</small>
              <small className="identifier">{runner.current?.plan.transactions[receipt.transactionIndex].offerKey}</small></td>
            <td><small>{receipt.command === 'placeOrder' ? 'Order' : 'Playback session'}</small>
              <code className="identifier">{receipt.result.entity_key}</code></td>
            <td>{receipt.result.event_ids.map(id => <div key={id}><code className="identifier">{id}</code>
              <small>{outbox.get(id)?.published_at ? 'Kafka ACK marker observed'
                : outbox.has(id) ? 'Outbox pending' : 'Not observed in current outbox read'}</small></div>)}</td>
            <td><span className="status">{receipt.result.status}</span>
              <small className="identifier">{receipt.idempotencyKey}</small></td>
          </tr>)}</tbody>
        </table></div>}
    </section>
  </>;
}
