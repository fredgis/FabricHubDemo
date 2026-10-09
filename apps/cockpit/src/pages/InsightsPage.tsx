import { useEffect, useId, useState, type FormEvent } from 'react';
import { ArrowsClockwise, ChartLine, SlidersHorizontal } from '@phosphor-icons/react';
import { DailyChart, PlaybackArc, TerritoryHeatmap } from '@/components/InsightsCharts';
import { InsightsCinema } from '@/components/InsightsCinema';
import { InsightsGeography } from '@/components/InsightsGeography';
import { useGoldInsights } from '@/hooks/useGoldInsights';
import { dateLabel } from '@/services/business';
import { addDays, currencyLabel, dailySeries, daysBetween, shortDay } from '@/services/insightsPresentation';
import type { GoldInsights, GoldInsightsFilters } from '@/services/insights';
import './InsightsPage.css';

const number = new Intl.NumberFormat('en');
export type InsightsReadState = { loading: boolean; queriedAt: string | null };

function Filters({ data, loading, onApply }: {
  data: GoldInsights; loading: boolean; onApply: (filters: Partial<GoldInsightsFilters>) => void;
}) {
  const id = useId();
  const [draft, setDraft] = useState(data.filters);
  const [validation, setValidation] = useState('');
  useEffect(() => { setDraft(data.filters); setValidation(''); }, [data]);
  const duration = daysBetween(draft.from, draft.to);
  const change = (field: keyof GoldInsightsFilters, value: string) => {
    setDraft(current => ({ ...current, [field]: value }));
    setValidation('');
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!Number.isInteger(duration) || duration < 1 || duration > 366) {
      setValidation('Choose an inclusive date range of 1 to 366 days.');
      return;
    }
    onApply(draft);
  };
  return <form className="insights-filter" onSubmit={submit} aria-label="Filter Gold analysis">
    <div className="insights-filter-heading"><div><h2><SlidersHorizontal size={20} aria-hidden="true" />Your analysis window</h2>
      <p>One selection across sales, catalogue, customers and associated playback.</p></div>
      <button type="button" disabled={loading} onClick={() => onApply({})}>Reset filters</button></div>
    <fieldset disabled={loading} style={{ border: 0, padding: 0, margin: 0 }}><legend className="sr-only">Gold order cohort filters</legend>
      <div className="insights-filter-fields">
        <label htmlFor={`${id}-from`}>From (UTC)<input id={`${id}-from`} type="date" required value={draft.from}
          max={draft.to} onChange={event => change('from', event.target.value)} aria-invalid={!!validation} aria-describedby={validation ? `${id}-error` : undefined} /></label>
        <label htmlFor={`${id}-to`}>To (UTC)<input id={`${id}-to`} type="date" required value={draft.to}
          min={draft.from} onChange={event => change('to', event.target.value)} aria-invalid={!!validation} aria-describedby={validation ? `${id}-error` : undefined} /></label>
        <label htmlFor={`${id}-territory`}>Territory<select id={`${id}-territory`} value={draft.territory} onChange={event => change('territory', event.target.value)}>
          <option value="">All territories</option>{data.options.territories.map(value => <option key={value}>{value}</option>)}</select></label>
        <label htmlFor={`${id}-genre`}>Genre<select id={`${id}-genre`} value={draft.genre} onChange={event => change('genre', event.target.value)}>
          <option value="">All genres</option>{data.options.genres.map(value => <option key={value}>{value}</option>)}</select></label>
        <label htmlFor={`${id}-type`}>Transaction<select id={`${id}-type`} value={draft.transactionType} onChange={event => change('transactionType', event.target.value)}>
          <option value="">Rentals + purchases</option><option value="TVOD">Rentals (TVOD)</option><option value="EST">Purchases (EST)</option></select></label>
        <label htmlFor={`${id}-currency`}>Currency<select id={`${id}-currency`} required value={draft.currency}
          aria-describedby={draft.currency === '*' ? `${id}-currency-note` : undefined} onChange={event => change('currency', event.target.value)}>
          <option value="*">ALL</option>{data.options.currencies.map(value => <option key={value} value={value}>{currencyLabel(value)}</option>)}</select></label>
      </div>
      {draft.currency === '*' && <p id={`${id}-currency-note`}>ALL adds nominal amounts across currencies, without exchange-rate conversion.</p>}
      <div className="insights-filter-actions"><label className="insights-window" htmlFor={`${id}-window`}>
        <span className="insights-window-title"><span>Window ending on {draft.to ? shortDay(draft.to) : 'the selected date'}</span>
          <output htmlFor={`${id}-window`}>{Number.isFinite(duration) ? duration : 0} days</output></span>
        <input id={`${id}-window`} type="range" min="1" max="366" step="1" value={Math.max(1, Math.min(366, duration || 1))}
          disabled={!draft.to} onChange={event => change('from', addDays(draft.to, 1 - Number(event.target.value)))}
          aria-valuetext={`${duration} days ending ${draft.to}`} />
      </label><button type="submit" className="primary">{loading ? 'Reading Gold…' : 'Apply filters'}</button></div>
    </fieldset>
    {validation && <p className="insights-field-error" id={`${id}-error`} role="alert">{validation}</p>}
  </form>;
}

function Sources({ data }: { data: GoldInsights }) {
  return <section className="insights-provenance" aria-labelledby="insights-provenance-title">
    <h2 id="insights-provenance-title">Where the picture comes from</h2>
    <p>{data.source.name} · Published {data.freshness.published_at ? dateLabel(data.freshness.published_at) : 'not yet'}.
      {' '}Read {dateLabel(data.freshness.queried_at)}. Publication time is not a live-source health check.</p>
    <ul className="insights-source-list">{data.sources.map(source => <li key={source.name} className={source.state === 'not-published' ? 'insights-source-unpublished' : undefined}>
      <div className="insights-source-label"><strong>{source.name}</strong><span>{source.state === 'published' ? 'In Gold' : 'Not published'}</span></div>
      <p>{source.detail}</p>{!!source.tables.length && <details><summary>{source.name} Gold tables</summary>{source.tables.map(table => <code key={table}>{table}</code>)}</details>}
    </li>)}</ul>
    <details className="insights-method"><summary>How to read these figures</summary><ul>
      <li>All figures query the complete matching Gold facts, not the cockpit's latest-activity lists. Dates select orders and are inclusive, in UTC.</li>
      <li>Booked sales are exact recorded amounts. A single currency keeps its original units. ALL adds nominal amounts across currencies without exchange-rate conversion, so it is not a comparable financial total. These are not payments, invoices or margin.</li>
      <li>Playback is associated with the selected order cohort. A session can occur after the order date. Position is playback progress, not time watched.</li>
      <li>Consent counts use the latest effective marketing consent at publication for cohort customers. Campaign inventory covers the selected territory, across all dates. Touches use cohort customers and the selected dates; conversions must match their orders. These are not causal sales attribution.</li>
      <li>The genre matrix shows up to 12 leading genres. Totals, daily series and territory figures are not capped to those genres. Territories are commercial order locations, not customer residences.</li>
      <li>SAP is excluded from financial claims unless its tables are actually published. Customer identities in this demonstration are fictional Salesforce records.</li>
    </ul></details>
  </section>;
}

function Audience({ data }: { data: GoldInsights }) {
  const audience = data.audience;
  const nullableCount = (value: number | null) => value === null ? 'Not available' : number.format(value);
  return <aside className="insights-audience-panel" aria-labelledby="insights-playback-title">
    <div className="insights-panel-heading"><div><h2 id="insights-playback-title">Do the orders reach the screen?</h2>
      <p>Recorded playback associated with this order cohort.</p></div></div>
    <PlaybackArc {...data.summary} />
    <div className="insights-crm"><h3>The Salesforce connection</h3><dl>
      <div><dt>Customers in cohort</dt><dd>{number.format(audience.customerCount)}</dd></div>
      <div><dt>Contactable customers</dt><dd>{nullableCount(audience.contactableCustomers)}</dd></div>
      <div><dt>Campaigns in territory</dt><dd>{number.format(audience.campaigns)}</dd></div>
      <div><dt>Recorded CRM touches</dt><dd>{nullableCount(audience.touches)}</dd></div>
    </dl><p>Consents at publication; campaign inventory across all dates. Touches use the selected customers and dates, without causal sales attribution.</p>
      {audience.conversions !== null && <p>{number.format(audience.conversions)} recorded campaign conversions for these customers.</p>}
    </div>
  </aside>;
}

export function InsightsPage({ active, refreshKey, onRead }: {
  active: boolean; refreshKey: number; onRead?: (state: InsightsReadState) => void;
}) {
  const { data, loading, error, apply, refresh } = useGoldInsights(active, refreshKey);
  const queriedAt = data?.freshness.queried_at ?? null;
  useEffect(() => { onRead?.({ loading, queriedAt }); }, [loading, queriedAt, onRead]);
  const applyFilters = (filters: Partial<GoldInsightsFilters>) => { void apply(filters); };
  const ready = data && data.state !== 'unpublished';
  return <div className="insights-page" aria-label="MSFlix Gold insights" aria-busy={loading}>
    {!data && !error && <section className="insights-initial"><h2>Connecting the business picture</h2>
      <p role="status">Reading the published Gold Warehouse: order facts, catalogue, customer context and playback. No operational sample is substituted.</p>
      <div className="insights-loading-lines" aria-hidden="true"><span /><span /><span /><span /><span /><span /></div></section>}
    {error && <section className="insights-status insights-status-error" role="alert"><h2>Gold analysis could not be read</h2>
      <p>{data ? 'The last successful selection and figures remain below. ' : 'No sample or operational fallback is shown. '}{error}</p>
      <button type="button" disabled={loading} onClick={() => void refresh()}><ArrowsClockwise aria-hidden="true" />Retry Gold analysis</button></section>}
    {ready && <>
      {data.state === 'ready' && <InsightsCinema data={data} />}
      <Filters data={data} loading={loading} onApply={applyFilters} />
      <div className="insights-selection" aria-label="Applied analysis filters"><strong>{shortDay(data.filters.from)} to {shortDay(data.filters.to)}, UTC</strong>
        <span>{data.filters.territory || 'All territories'}</span><span>{data.filters.genre || 'All genres'}</span>
        <span>{data.filters.transactionType === 'TVOD' ? 'Rentals' : data.filters.transactionType === 'EST' ? 'Purchases' : 'Rentals + purchases'}</span>
        <strong>{currencyLabel(data.filters.currency)}{data.filters.currency !== '*' && ' only'}</strong></div>
      {loading && <p className="insights-status" role="status">Updating the analysis. The last successful selection remains visible.</p>}
      {data.state === 'empty' ? <section className="insights-initial"><h2>No orders match this selection</h2>
        <p>Gold is published, but this combination has no matching order facts. Widen the dates or reset the filters to the latest available data.</p>
        <div><button type="button" disabled={loading} onClick={() => applyFilters({})}>Use latest data window</button></div></section> : <>
        <div className="insights-analysis">
          <section className="insights-trend-panel" aria-label="Sales and order trend"><div className="insights-panel-heading"><div><h2>When does the business happen?</h2>
            <p>Daily order cohorts. Switch the measure, then inspect a day.</p></div><ChartLine size={24} aria-hidden="true" /></div>
            <DailyChart key={JSON.stringify(data.filters)} days={dailySeries(data.daily, data.filters.from, data.filters.to)} currency={data.filters.currency} />
          </section><Audience data={data} />
        </div>
        <InsightsGeography data={data} disabled={loading} onSelect={territory => applyFilters({ ...data.filters, territory })} />
        <section className="insights-heat-panel" aria-labelledby="insights-heat-title">
          <div className="insights-panel-heading"><div><h2 id="insights-heat-title">Which stories travel?</h2>
            <p>Territory × genre. Select a cell to cross-filter the entire dashboard. Up to 12 leading genres are shown.</p></div></div>
          <TerritoryHeatmap cells={data.heatmap} currency={data.filters.currency} disabled={loading}
            onSelect={(territory, genre) => applyFilters({ ...data.filters, territory, genre })} />
        </section>
      </>}
    </>}
    {data?.state === 'unpublished' && <section className="insights-initial"><h2>Gold is not published yet</h2>
      <p>No completed Gold publication is available. This dashboard does not substitute operational data or pretend that SAP is connected.</p>
      <div><button type="button" disabled={loading} onClick={() => void refresh()}>Check publication again</button></div></section>}
    {data && <Sources data={data} />}
  </div>;
}
