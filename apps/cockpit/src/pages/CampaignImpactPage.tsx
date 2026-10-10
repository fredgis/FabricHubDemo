import { useEffect, useId, useState, type FormEvent } from 'react';
import { ArrowsClockwise } from '@phosphor-icons/react';
import { useCampaignImpact } from '@/hooks/useCampaignImpact';
import { dateLabel } from '@/services/business';
import { currencyLabel, daysBetween, share, shortDay } from '@/services/insightsPresentation';
import { campaignMoney, largestMinor, titleContributions, type CampaignMoney, type ContributionGroup } from '@/services/campaignImpactPresentation';
import type { CampaignImpact, CampaignImpactFilters } from '@/services/campaignImpact';
import './InsightsPage.css';
import './CampaignImpactPage.css';

const number = new Intl.NumberFormat('en');
const rateLabel = 'Engaged revenue per 100 contacted customers';
export type CampaignImpactReadState = { loading: boolean; queriedAt: string | null };

function Filters({ data, loading, onApply }: {
  data: CampaignImpact; loading: boolean; onApply: (filters: Partial<CampaignImpactFilters>) => void;
}) {
  const id = useId();
  const [draft, setDraft] = useState(data.filters);
  const [validation, setValidation] = useState('');
  useEffect(() => { setDraft(data.filters); setValidation(''); }, [data]);
  const change = (field: keyof CampaignImpactFilters, value: string) => {
    setDraft(current => ({ ...current, [field]: value }));
    setValidation('');
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const duration = daysBetween(draft.from, draft.to);
    if (!Number.isInteger(duration) || duration < 1 || duration > 366) {
      setValidation('Choose an inclusive date range of 1 to 366 days.');
      return;
    }
    onApply(draft);
  };
  return <form className="insights-filter campaign-filters" aria-label="Filter campaign impact" onSubmit={submit}>
    <div className="insights-filter-heading"><div><h2>Choose the contact cohort</h2>
      <p>Dates select each customer's first contact in a campaign. One currency at a time.</p></div>
      <button type="button" disabled={loading} onClick={() => onApply({})}>Reset filters</button></div>
    <fieldset disabled={loading}><legend className="sr-only">First campaign contact filters</legend>
      <div className="insights-filter-fields">
        <label htmlFor={`${id}-from`}>From (UTC)<input id={`${id}-from`} type="date" required value={draft.from} max={draft.to}
          onChange={event => change('from', event.target.value)} aria-invalid={!!validation} aria-describedby={validation ? `${id}-error` : undefined} /></label>
        <label htmlFor={`${id}-to`}>To (UTC)<input id={`${id}-to`} type="date" required value={draft.to} min={draft.from}
          onChange={event => change('to', event.target.value)} aria-invalid={!!validation} aria-describedby={validation ? `${id}-error` : undefined} /></label>
        <label htmlFor={`${id}-territory`}>Territory<select id={`${id}-territory`} value={draft.territory} onChange={event => change('territory', event.target.value)}>
          <option value="">All territories</option>{data.options.territories.map(value => <option key={value}>{value}</option>)}</select></label>
        <label htmlFor={`${id}-campaign`}>Campaign<select id={`${id}-campaign`} value={draft.campaignKey} onChange={event => change('campaignKey', event.target.value)}>
          <option value="">All campaigns</option>{data.options.campaigns.map(campaign => <option key={campaign.campaign_key} value={campaign.campaign_key}>{campaign.name}</option>)}</select></label>
        <label htmlFor={`${id}-currency`}>Currency<select id={`${id}-currency`} value={draft.currency} required onChange={event => change('currency', event.target.value)}>
          {!data.options.currencies.length && <option value="">No currency published</option>}
          {data.options.currencies.map(option => <option key={option.currency} value={option.currency}>{currencyLabel(option.currency)}</option>)}</select></label>
      </div>
      <div className="campaign-filter-actions"><p>Contacts include non-buyers and do not change with currency.</p>
        <button type="submit" className="primary">{loading ? 'Reading Gold…' : 'Apply filters'}</button></div>
    </fieldset>
    {validation && <p className="insights-field-error" id={`${id}-error`} role="alert">{validation}</p>}
  </form>;
}

function Spotlight({ data, money }: { data: CampaignImpact; money: CampaignMoney }) {
  const summary = data.summary;
  const counts = [
    ['Contacted customers', summary.contacted_customers], ['Recorded contacts', summary.touches],
    ['Buyers', summary.buyers], ['All eligible orders', summary.orders],
    ['Started orders', summary.played_orders], ['Engaged orders', summary.engaged_orders],
  ] as const;
  return <section className="campaign-spotlight" aria-labelledby="campaign-rate-title">
    <div className="campaign-rate-block"><h2 id="campaign-rate-title">{rateLabel}</h2>
      <p className="campaign-rate" aria-label={rateLabel}>{money(summary.engaged_per_100_minor)}</p>
      <p className="campaign-note">{summary.engaged_per_100_minor === null
        ? `The rate is not available. Denominator: ${number.format(summary.contacted_customers)} unique contacted customers.`
        : `100 × ${money(summary.engaged_minor)} engaged booked value / ${number.format(summary.contacted_customers)} unique contacted customers.`}</p>
      <p className="campaign-note">Booked order value, not recognized revenue or ROI. Recent cohorts are provisional.</p>
      {summary.contacted_customers > 0 && summary.orders === 0 && <p className="campaign-note">No eligible campaign-linked orders are recorded for this cohort. Unattributed purchases do not enter this rate.</p>}</div>
    <dl className="campaign-money-ledger">
      <div><dt>All eligible booked value</dt><dd>{money(summary.booked_minor)}</dd></div>
      <div><dt>Engaged booked value</dt><dd>{money(summary.engaged_minor)}</dd></div>
      <div><dt>Not-started booked value</dt><dd>{money(summary.not_started_minor)}</dd></div>
    </dl>
    <dl className="campaign-counts">{counts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{number.format(value)}</dd></div>)}</dl>
    <p className="campaign-note">Engaged means furthest playback position reached {data.methodology.engagement_percent}% of the Oracle duration.
      {' '}This is progression, not watch time. {number.format(summary.unknown_duration_orders)} orders have unknown duration.</p>
  </section>;
}

function CampaignComparison({ data, money }: { data: CampaignImpact; money: CampaignMoney }) {
  const maximum = largestMinor(data.campaigns.map(row => row.engaged_per_100_minor));
  return <section aria-labelledby="campaign-comparison-title">
    <div className="insights-panel-heading"><div><h2 id="campaign-comparison-title">Which campaigns reach engaged orders?</h2>
      <p>Compare the rate alongside each campaign's contact denominator. Contact counts are distinct within each scope, not additive.</p></div></div>
    {!data.campaigns.length ? <p className="campaign-note">No campaign rows were returned for this contact cohort.</p> :
      <div className="campaign-table-scroll" role="region" aria-label="Campaign comparison figures" tabIndex={0}>
        <table className="campaign-table"><caption className="sr-only">Campaign comparison in {data.filters.currency}. Started and engaged counts are subsets of all eligible orders.</caption>
          <thead><tr><th scope="col">Campaign</th><th scope="col">Engaged per 100 contacts</th><th scope="col">Contacted customers</th>
            <th scope="col">Buyers</th><th scope="col">All orders</th><th scope="col">Started orders</th><th scope="col">Engaged orders</th></tr></thead>
          <tbody>{data.campaigns.map(row => <tr key={row.campaign_key}>
            <th scope="row">{row.name}</th><td><strong>{money(row.engaged_per_100_minor)}</strong>
              <span className="campaign-bar" aria-hidden="true"><span style={{ width: `${share(row.engaged_per_100_minor ?? '0', maximum)}%` }} /></span></td>
            <td>{number.format(row.contacted_customers)}</td><td>{number.format(row.buyers)}</td><td>{number.format(row.orders)}</td>
            <td>{number.format(row.played_orders)}</td><td>{number.format(row.engaged_orders)}</td>
          </tr>)}</tbody>
        </table>
      </div>}
  </section>;
}

function CohortTrend({ data, money }: { data: CampaignImpact; money: CampaignMoney }) {
  const id = useId();
  const days = [...data.trend].sort((left, right) => left.date.localeCompare(right.date));
  const maximum = largestMinor(days.map(day => day.engaged_per_100_minor));
  const length = daysBetween(data.filters.from, data.filters.to);
  const step = 660 / Math.max(length, 1);
  return <section className="campaign-trend" aria-labelledby="campaign-trend-title">
    <div className="insights-panel-heading"><div><h2 id="campaign-trend-title">First-contact cohort trend</h2>
      <p>{rateLabel}, by first contact date. Later eligible orders stay with that cohort.</p></div></div>
    {!days.length ? <p className="campaign-note">No first-contact dates were returned for this selection.</p> : <>
      <figure className="campaign-trend-figure">
        <figcaption>Peak rate: <strong>{days.some(day => day.engaged_per_100_minor !== null) ? money(maximum) : 'Not available'}</strong></figcaption>
        <svg viewBox="0 0 720 230" role="img" aria-labelledby={`${id}-title ${id}-description`}>
          <title id={`${id}-title`}>{rateLabel} by first contact date</title>
          <desc id={`${id}-description`}>Daily rates in {data.filters.currency}. No bar is drawn for an unavailable rate. Exact values and denominators are in the cohort figures table.</desc>
          <line x1="30" x2="690" y1="190" y2="190" className="campaign-chart-baseline" />
          {days.filter(day => day.engaged_per_100_minor !== null).map(day => {
            const height = share(day.engaged_per_100_minor ?? '0', maximum) * 1.55;
            const x = 30 + (daysBetween(data.filters.from, day.date) - .5) * step;
            return <rect key={day.date} x={x - Math.min(step * .7, 30) / 2} y={190 - height}
              width={Math.min(step * .7, 30)} height={height} className="campaign-chart-bar" />;
          })}
          <text x="30" y="216">{shortDay(data.filters.from)}</text>
          <text x="690" y="216" textAnchor="end">{shortDay(data.filters.to)}</text>
        </svg>
      </figure>
      <details className="campaign-cohort-details"><summary>Exact cohort figures</summary>
        <div className="campaign-table-scroll" role="region" aria-label="First-contact cohort figures" tabIndex={0}>
          <table className="campaign-table"><caption className="sr-only">First contact dates in UTC, with distinct contacts and the returned daily rate.</caption>
            <thead><tr><th scope="col">First contact (UTC)</th><th scope="col">Engaged per 100 contacts</th><th scope="col">Contacted customers</th>
              <th scope="col">Buyers</th><th scope="col">All orders</th><th scope="col">Started orders</th><th scope="col">Engaged orders</th></tr></thead>
            <tbody>{days.map(day => <tr key={day.date}><th scope="row">{day.date}</th><td>{money(day.engaged_per_100_minor)}</td>
              <td>{number.format(day.contacted_customers)}</td><td>{number.format(day.buyers)}</td><td>{number.format(day.orders)}</td>
              <td>{number.format(day.played_orders)}</td><td>{number.format(day.engaged_orders)}</td></tr>)}</tbody>
          </table>
        </div>
        <p className="campaign-note">A customer may appear in more than one campaign or date. Do not sum these contact counts to reconstruct the overall denominator.</p>
      </details>
    </>}
  </section>;
}

function Contributions({ data, money }: { data: CampaignImpact; money: CampaignMoney }) {
  const [group, setGroup] = useState<ContributionGroup>('films');
  const rows = titleContributions(data.titles, group);
  const maximum = largestMinor(rows.map(row => row.engagedMinor));
  const labels = { films: 'Film', genres: 'Genre', distributors: 'Distributor' };
  return <section aria-labelledby="campaign-contribution-title">
    <div className="insights-panel-heading"><div><h2 id="campaign-contribution-title">The films behind engaged value</h2>
      <p>Contribution within the returned films, ranked by engaged booked value. Genre and distributor totals cover only these films.</p></div></div>
    <div className="insights-chart-tools" role="group" aria-label="Group film contribution">
      {(['films', 'genres', 'distributors'] as const).map(value => <button key={value} type="button" aria-pressed={group === value}
        onClick={() => setGroup(value)}>{value === 'films' ? 'Films' : value === 'genres' ? 'Genres' : 'Distributors'}</button>)}
    </div>
    {!rows.length ? <p className="campaign-note">No eligible film orders for this contact cohort.</p> : <div className="campaign-table-scroll" role="region" aria-label="Film contribution figures" tabIndex={0}>
      <table className="campaign-table campaign-contribution-table"><caption className="sr-only">{labels[group]} contribution to booked and engaged value in {data.filters.currency}.</caption>
        <thead><tr><th scope="col">{labels[group]}</th><th scope="col">Engaged booked value</th><th scope="col">All booked value</th></tr></thead>
        <tbody>{rows.map(row => <tr key={row.key}><th scope="row">{row.name}{row.detail && <small>{row.detail}</small>}</th>
          <td><strong>{money(row.engagedMinor)}</strong><span className="campaign-bar" aria-hidden="true"><span style={{ width: `${share(row.engagedMinor, maximum)}%` }} /></span></td>
          <td>{money(row.bookedMinor)}</td></tr>)}</tbody>
      </table>
    </div>}
  </section>;
}

function Coverage({ data, money }: { data: CampaignImpact; money: CampaignMoney }) {
  return <section className="campaign-coverage" aria-labelledby="campaign-coverage-title">
    <h2 id="campaign-coverage-title">Outside the attribution boundary</h2>
    <p className="campaign-note">Excluded orders created from {data.filters.from} to {data.filters.to}, inclusive UTC, with the same territory, currency and campaign filters.
      {' '}This is an order-date scope, separate from the first-contact cohort. Their booked value does not enter the KPI.</p>
    <dl className="campaign-coverage-counts">
      <div><dt>Unattributed orders</dt><dd>{number.format(data.coverage.unattributed_orders)}</dd></div>
      <div><dt>Ambiguous campaign links</dt><dd>{number.format(data.coverage.ambiguous_orders)}</dd></div>
      <div><dt>Linked without prior contact</dt><dd>{number.format(data.coverage.linked_without_touch_orders)}</dd></div>
      <div><dt>Excluded booked value</dt><dd>{money(data.coverage.excluded_minor)}</dd></div>
    </dl>
    <p className="campaign-note">Unattributed orders appear only with All campaigns.</p>
  </section>;
}

function Sources({ data }: { data: CampaignImpact }) {
  return <section className="insights-provenance campaign-sources" aria-labelledby="campaign-sources-title">
    <h2 id="campaign-sources-title">Three sources, one Gold snapshot</h2>
    <p>{data.source.name} · <code>{data.source.view}</code></p>
    <p>Gold published {data.freshness.published_at ? dateLabel(data.freshness.published_at) : 'not yet'}.
      {' '}Read {dateLabel(data.freshness.queried_at)}. This is the current Gold snapshot, not a direct Eventhouse real-time feed.</p>
    <ul className="insights-source-list">
      <li><strong>Salesforce</strong><p>Campaign contacts and recorded order attribution.</p></li>
      <li><strong>Oracle</strong><p>Film, genre, distributor and reference duration.</p></li>
      <li><strong>RTI</strong><p>Order facts and furthest recorded playback position.</p></li>
    </ul>
    <details className="insights-method"><summary>Attribution and engagement methodology</summary><ul>
      <li>The first contact for each campaign and customer sets the cohort date. Dates are inclusive UTC. The denominator counts unique contacted customers in the requested scope, including non-buyers, regardless of currency.</li>
      <li>Only recorded campaign links with a contact at or before purchase qualify. There is no inferred last-touch attribution or contact-window cap. Later purchases can belong to an earlier contact cohort. These associations do not establish causality.</li>
      <li>Engagement requires the furthest RTI playback position for that order, customer and film to reach at least {data.methodology.engagement_percent}% of the Oracle duration. It is a progression proxy, not watch time; missing duration is unknown.</li>
      <li>The KPI is 100 × engaged booked value / unique contacted customers, rounded to the currency's minor unit. Currencies remain separate. Booked value is not recognized revenue or ROI, and recent cohorts are provisional.</li>
    </ul></details>
  </section>;
}

export function CampaignImpactPage({ active, refreshKey, onRead }: {
  active: boolean; refreshKey: number; onRead?: (state: CampaignImpactReadState) => void;
}) {
  const { data, loading, error, apply, refresh } = useCampaignImpact(active, refreshKey);
  const queriedAt = data?.freshness.queried_at ?? null;
  useEffect(() => { onRead?.({ loading, queriedAt }); }, [loading, queriedAt, onRead]);
  const applyFilters = (filters: Partial<CampaignImpactFilters>) => { void apply(filters); };
  const published = data && data.state !== 'unpublished';
  const exponent = data?.options.currencies.find(option => option.currency === data.filters.currency)?.minor_exponent;
  const money = campaignMoney(data?.filters.currency ?? '', exponent);
  return <div className="insights-page campaign-impact" aria-label="MSFlix campaign impact" aria-busy={loading}>
    {!data && !error && <section className="insights-initial"><h2>Reading campaign impact</h2>
      <p role="status">Reading the published Gold contact cohorts, recorded orders and playback progression. No sample figures are substituted.</p></section>}
    {error && <section className="insights-status insights-status-error" role="alert"><h2>Campaign impact could not be read</h2>
      <p>{data ? 'The last successful selection and figures remain below. ' : 'No sample figures are shown. '}{error}</p>
      <button type="button" disabled={loading} onClick={() => void refresh()}><ArrowsClockwise aria-hidden="true" />Retry campaign impact</button></section>}
    {published && <>
      <Filters data={data} loading={loading} onApply={applyFilters} />
      <div className="insights-selection" aria-label="Applied campaign filters">
        <strong>First contact: {data.filters.from} to {data.filters.to}, UTC</strong><span>{data.filters.territory || 'All territories'}</span>
        <span>{data.options.campaigns.find(campaign => campaign.campaign_key === data.filters.campaignKey)?.name || data.filters.campaignKey || 'All campaigns'}</span>
        <strong>{data.filters.currency ? `${currencyLabel(data.filters.currency)} only` : 'Currency not published'}</strong>
      </div>
      {loading && <p className="insights-status" role="status">Updating campaign impact. The last successful selection remains visible.</p>}
      {exponent === undefined && <p className="campaign-note">Currency units are not published for this selection. Monetary values are not available.</p>}
      {data.state === 'empty' ? <section className="insights-initial"><h2>No contacts or eligible orders match this cohort</h2>
        <p>{rateLabel}: Not available. There are no contacted customers for the denominator. Widen the dates or reset the filters. Excluded orders, if any, remain visible below.</p>
        <div><button type="button" disabled={loading} onClick={() => applyFilters({})}>Use latest contact window</button></div></section> : <>
        <Spotlight data={data} money={money} />
        <CampaignComparison data={data} money={money} />
        <CohortTrend data={data} money={money} />
        <Contributions data={data} money={money} />
      </>}
      <Coverage data={data} money={money} />
    </>}
    {data?.state === 'unpublished' && <section className="insights-initial"><h2>Campaign impact is not published yet</h2>
      <p>The Gold campaign view is not available in a completed publication. No operational data or invented conversions replace it.</p>
      <div><button type="button" disabled={loading} onClick={() => void refresh()}>Check publication again</button></div></section>}
    {data && <Sources data={data} />}
  </div>;
}
